from django import forms

class ReviewReasonForm(forms.Form):
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        label="Reason / Notes"
    )


class ReportFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    owner_id = forms.IntegerField(required=False)
    asset_id = forms.IntegerField(required=False)