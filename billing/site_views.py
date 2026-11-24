"""Public website pages: contact, privacy policy, terms."""
import logging
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render
from django.utils import timezone

from core.forms import StyledMixin
from core.services import client_ip

from .models import ContactMessage, SiteSettings

log = logging.getLogger(__name__)
MAX_PER_HOUR = 5


class ContactForm(StyledMixin, forms.ModelForm):
    website = forms.CharField(required=False, label="Leave this empty")  # spam trap, hidden from people

    class Meta:
        model = ContactMessage
        fields = ["name", "organisation", "email", "phone", "staff_count", "message"]
        labels = {"organisation": "School or organisation", "staff_count": "Number of staff (roughly)"}
        widgets = {"message": forms.Textarea(attrs={"rows": 5, "placeholder": "How can we help?"})}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["website"].widget.attrs.update({"tabindex": "-1", "autocomplete": "off"})
        self._style()

    def clean(self):
        cd = super().clean()
        if not cd.get("email") and not cd.get("phone"):
            raise forms.ValidationError("Leave an email address or a phone number so we can reply.")
        return cd


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ip = client_ip(request)
        recent = ContactMessage.objects.filter(ip=ip, created_at__gte=timezone.now() - timedelta(hours=1)).count()
        if form.cleaned_data.get("website"):           # a bot filled the hidden field: pretend it worked
            messages.success(request, "Thanks! We'll get back to you shortly.")
            return redirect("contact")
        if recent >= MAX_PER_HOUR:
            messages.error(request, "You've sent several messages already. Please try again later, or call us.")
            return redirect("contact")
        msg = form.save(commit=False)
        msg.ip = ip
        msg.save()
        _email_team(msg)
        messages.success(request, "Thanks! Your message has reached us. We'll reply as soon as we can.")
        return redirect("contact")
    return render(request, "public/contact.html", {"form": form})


def _email_team(msg):
    site = SiteSettings.load()
    to = [e for e in (site.sales_email, site.contact_email) if e]
    if not to or not settings.EMAIL_HOST:
        return
    body = (f"From: {msg.name} ({msg.organisation or 'no organisation given'})\nEmail: {msg.email or '—'}\n"
            f"Phone: {msg.phone or '—'}\nStaff: {msg.staff_count or '—'}\n\n{msg.message}")
    try:
        EmailMessage(f"AttendPro enquiry from {msg.name}", body, to=to[:1],
                     reply_to=[msg.email] if msg.email else None).send()
    except Exception:
        log.exception("Couldn't email contact message %s", msg.pk)


def privacy(request):
    return render(request, "public/privacy.html", {"effective": "24 November 2026"})


def terms(request):
    return render(request, "public/terms.html", {"effective": "24 November 2026"})
