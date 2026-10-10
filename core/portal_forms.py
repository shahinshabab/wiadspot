from django import forms
from ads.models import Asset


class CampaignSubmissionForm(forms.Form):
    name = forms.CharField(label="Campaign name", max_length=255)
    title = forms.CharField(label="Poster title", max_length=255)
    poster = forms.ImageField(help_text="JPEG, PNG or WebP. Maximum 10 MB.")
    target_url = forms.URLField(label="Destination URL", required=False)
    location = forms.ModelChoiceField(
        queryset=Asset.objects.none(), empty_label="Choose a location"
    )

    def __init__(self, *args, user, role, **kwargs):
        super().__init__(*args, **kwargs)
        locations = Asset.objects.filter(status="ACTIVE", is_available_for_booking=True)
        if role == "owner":
            locations = locations.filter(partner=user, owner_type="PARTNER")
        self.fields["location"].queryset = locations
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-select"
                if isinstance(field, forms.ModelChoiceField)
                else "form-control"
            )
        self.fields["poster"].widget.attrs["accept"] = "image/jpeg,image/png,image/webp"

    def clean_poster(self):
        poster = self.cleaned_data["poster"]
        if poster.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Choose an image smaller than 10 MB.")
        if poster.image.format not in {"JPEG", "PNG", "WEBP"}:
            raise forms.ValidationError("Choose a JPEG, PNG or WebP image.")
        return poster
