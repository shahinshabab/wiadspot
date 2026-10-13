from decimal import Decimal
from urllib.parse import urlsplit

from django import forms
from django.forms import modelformset_factory

from ads.models import SubscriptionPlan

from . import media, rules
from .models import LocationRequest, MarketplaceSettings, SpotProfile, Town


def _style(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxInput,)):
            widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(widget, forms.Select):
            widget.attrs.setdefault("class", "form-select")
        elif not isinstance(widget, (forms.HiddenInput, forms.MultipleHiddenInput)):
            widget.attrs.setdefault("class", "form-control")


class AdSubmissionForm(forms.Form):
    name = forms.CharField(label="Campaign name", max_length=255)
    title = forms.CharField(label="Ad title", max_length=255)
    media_file = forms.FileField(label="Ad image or video")
    target_url = forms.URLField(label="Destination link (optional)", required=False)
    spots = forms.ModelMultipleChoiceField(
        queryset=SpotProfile.objects.none(), label="Locations",
        error_messages={"required": "Choose at least one location."},
    )
    total_budget = forms.DecimalField(
        label="Total budget (₹)", min_value=Decimal("0"), max_digits=12, decimal_places=2,
        help_text="The most this campaign can ever spend. Delivery stops when it is used up.",
    )
    daily_budget = forms.DecimalField(
        label="Daily budget (₹)", required=False, min_value=Decimal("1"), max_digits=12,
        decimal_places=2, help_text="Optional. The most it can spend in one day.",
    )
    max_views = forms.IntegerField(
        label="Maximum views", required=False, min_value=1, max_value=100_000_000,
        help_text="Optional. Stop after this many users have seen the ad.",
    )
    start_date = forms.DateField(label="Start date", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label="End date", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, user, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.user, self.role = user, role
        self.conf = MarketplaceSettings.load()
        self.fields["spots"].queryset = rules.spots_for_booking(user, role)
        self.fields["media_file"].widget.attrs["accept"] = "image/jpeg,image/png,image/webp,video/mp4"
        _style(self)
        self.processed = None

    def clean_target_url(self):
        url = self.cleaned_data["target_url"]
        if url and urlsplit(url).scheme not in ("http", "https"):
            raise forms.ValidationError("Use an http:// or https:// link.")
        return url

    def clean_media_file(self):
        upload = self.cleaned_data["media_file"]
        head = upload.read(12)
        upload.seek(0)
        try:
            if head[4:8] == b"ftyp":
                self.processed = ("VIDEO", *media.process_video(upload, self.conf))
            else:
                self.processed = ("IMAGE", *media.process_image(upload, self.conf))
        except media.MediaError as exc:
            raise forms.ValidationError(str(exc))
        return upload

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The end date must be after the start date.")
        total, daily = data.get("total_budget"), data.get("daily_budget")
        if total is not None and daily and daily > total:
            self.add_error("daily_budget", "The daily budget can't be more than the total budget.")
        return data

    @property
    def processed_file(self):
        return self.processed[1]

    @property
    def processed_type(self):
        return self.processed[0]


class LocationRequestForm(forms.ModelForm):
    town = forms.ModelChoiceField(queryset=Town.objects.filter(is_active=True), empty_label="Choose a town")

    class Meta:
        model = LocationRequest
        fields = ["name", "town", "address", "contact_phone", "notes"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}
        labels = {"name": "Location name", "contact_phone": "Contact phone"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].required = True
        self.fields["contact_phone"].required = True
        _style(self)


class ListingForm(forms.Form):
    asset_id = forms.IntegerField(widget=forms.HiddenInput)
    town = forms.ModelChoiceField(queryset=Town.objects.filter(is_active=True), empty_label="Choose a town")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class WithdrawalForm(forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"))
    payout_details = forms.CharField(
        label="Bank account or UPI details", widget=forms.Textarea(attrs={"rows": 3}), max_length=1000
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class SettingsForm(forms.ModelForm):
    class Meta:
        model = MarketplaceSettings
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)

    def _clean_rate(self, name):
        value = self.cleaned_data[name]
        if value is None or value < 0:
            raise forms.ValidationError("Enter zero or more.")
        if value != value.quantize(Decimal("0.01")):
            raise forms.ValidationError("Use at most two decimal places (wallets hold rupees and paise).")
        return value

    def clean_company_rate_per_view(self):
        return self._clean_rate("company_rate_per_view")

    def clean_partner_rate_per_view(self):
        return self._clean_rate("partner_rate_per_view")

    def clean_owner_share_percent(self):
        value = self.cleaned_data["owner_share_percent"]
        if not Decimal("0") <= value <= Decimal("100"):
            raise forms.ValidationError("Enter a percentage from 0 to 100.")
        return value

    def clean(self):
        data = super().clean()
        if data.get("video_min_seconds") and data.get("video_max_seconds"):
            if data["video_min_seconds"] > data["video_max_seconds"]:
                self.add_error("video_min_seconds", "The minimum can't exceed the maximum length.")
        for name in ("image_width", "image_height", "video_width", "video_height", "image_max_mb", "video_max_mb"):
            if name in data and data[name] < 1:
                self.add_error(name, "Must be at least 1.")
        return data


class PlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = ["name", "monthly_price", "max_campaigns", "max_ads", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


PlanFormSet = modelformset_factory(SubscriptionPlan, form=PlanForm, extra=1, can_delete=False)


class SpotForm(forms.ModelForm):
    class Meta:
        model = SpotProfile
        fields = ["town", "mode", "rate_override"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["town"].queryset = Town.objects.filter(is_active=True)
        _style(self)

    def clean_rate_override(self):
        value = self.cleaned_data["rate_override"]
        if value is not None and value != value.quantize(Decimal("0.01")):
            raise forms.ValidationError("Use at most two decimal places.")
        return value


class WalletCreditForm(forms.Form):
    username = forms.CharField(max_length=150)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1"))
    reference = forms.CharField(max_length=100, required=False, label="Payment reference")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
