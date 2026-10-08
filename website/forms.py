from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags


# ---------
# Forms
# ---------
class ContactForm(forms.Form):
    name = forms.CharField(max_length=120)
    email = forms.EmailField()
    message = forms.CharField(widget=forms.Textarea, max_length=5000)
    # simple honeypot: should remain empty
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        # remove any HTML
        return strip_tags(name)

    def clean_message(self):
        msg = self.cleaned_data["message"].strip()
        # strip HTML tags to avoid stored XSS; Django autoescapes on render too
        msg = strip_tags(msg)
        # optional: block obvious spam payloads/URLs (tune as you like)
        bad_terms = ["http://", "https://", "[url]", "<a "]
        if any(t in msg.lower() for t in bad_terms):
            # You can choose to allow links by using a sanitizer like bleach instead.
            raise ValidationError("Please remove links from the message.")
        return msg

    def clean_website(self):
        # honeypot must be empty
        if self.cleaned_data.get("website"):
            raise ValidationError("Spam detected.")
        return ""
