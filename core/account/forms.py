"""
forms.py — ModelForms for User, Profile, Group
- Full validation (duplicates, required fields, password strength)
- Avatar upload with file-type validation
- Role (Group) assignment baked into User forms
"""

from django import forms
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from .models import UserProfile


# ─────────────────────────────────────────
# USER FORMS
# ─────────────────────────────────────────

class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Minimum 8 characters"}),
        min_length=8,
        label="Password",
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat password"}),
        label="Confirm Password",
    )
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=False,
        empty_label="— No Role —",
        label="Role / Group",
    )

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name"]
        widgets = {
            "username": forms.TextInput(attrs={"placeholder": "e.g. john_doe"}),
            "email": forms.EmailInput(attrs={"placeholder": "user@example.com"}),
        }

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            role = self.cleaned_data.get("role")
            user.groups.set([role] if role else [])
        return user


class UserEditForm(forms.ModelForm):
    role = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        required=False,
        empty_label="— No Role —",
        label="Role / Group",
    )
    is_active = forms.BooleanField(required=False, label="Active account")

    class Meta:
        model = User
        fields = ["username", "email", "first_name", "last_name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["role"].initial = self.instance.groups.first()

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This username is already taken.")
        return username

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            role = self.cleaned_data.get("role")
            user.groups.set([role] if role else [])
        return user


# ─────────────────────────────────────────
# PROFILE FORM
# ─────────────────────────────────────────

ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"]
MAX_AVATAR_SIZE_MB = 2


class UserProfileForm(forms.ModelForm):
    # email lives on User, not UserProfile — add it as an extra field
    email = forms.EmailField(
        required=False,
        label="Email Address",
        widget=forms.EmailInput(attrs={"placeholder": "your@email.com"}),
    )

    class Meta:
        model = UserProfile
        fields = ["avatar", "bio", "phone"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 3, "placeholder": "Tell us about yourself..."}),
            "phone": forms.TextInput(attrs={"placeholder": "+880 1700 000000"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate email from the related User instance
        if self.instance and self.instance.pk:
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email:
            # Check no other user already has this email
            qs = User.objects.filter(email__iexact=email)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.user.pk)
            if qs.exists():
                raise ValidationError("This email address is already in use.")
        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar:
            if hasattr(avatar, "content_type") and avatar.content_type not in ALLOWED_IMAGE_TYPES:
                raise ValidationError("Only JPEG, PNG, WebP, or GIF images are allowed.")
            if avatar.size > MAX_AVATAR_SIZE_MB * 1024 * 1024:
                raise ValidationError(f"Image must be under {MAX_AVATAR_SIZE_MB}MB.")
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=commit)
        # Save email back to the User model
        if commit:
            email = self.cleaned_data.get("email", "").strip()
            profile.user.email = email
            profile.user.save(update_fields=["email"])
        return profile


# ─────────────────────────────────────────
# GROUP FORM
# ─────────────────────────────────────────

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Editors, Managers"}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("Group name is required.")
        qs = Group.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("A group with this name already exists.")
        return name



# ─────────────────────────────────────────────────────────
# ATTENDANCE FORM
# ─────────────────────────────────────────────────────────
from .models import Attendance

class AttendanceForm(forms.ModelForm):
    class Meta:
        model  = Attendance
        fields = ["employee", "date", "check_in", "check_out", "status", "note"]
        widgets = {
            "employee":  forms.Select(attrs={"class": "form-control"}),
            "date":      forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "check_in":  forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "check_out": forms.TimeInput(attrs={"type": "time", "class": "form-control"}),
            "status":    forms.Select(attrs={"class": "form-control"}),
            "note":      forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}),
        }

    def clean(self):
        cleaned = super().clean()
        ci = cleaned.get("check_in")
        co = cleaned.get("check_out")
        if ci and co and co <= ci:
            raise forms.ValidationError("Check-out must be after check-in.")
        return cleaned


# ─────────────────────────────────────────────────────────
# OFFICE FORM
# ─────────────────────────────────────────────────────────
from .models import Office

class OfficeForm(forms.ModelForm):
    class Meta:
        model  = Office
        fields = ["name", "address", "latitude", "longitude", "allowed_radius",
                  "work_start", "work_end", "late_grace_minutes",
                  "half_day_start", "half_day_end", "is_active"]
        widgets = {
            "name":               forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Dhaka Head Office"}),
            "address":            forms.TextInput(attrs={"class": "form-control", "placeholder": "Full address"}),
            "latitude":           forms.NumberInput(attrs={"class": "form-control", "step": "0.0000001", "placeholder": "e.g. 23.8103000"}),
            "longitude":          forms.NumberInput(attrs={"class": "form-control", "step": "0.0000001", "placeholder": "e.g. 90.4125000"}),
            "allowed_radius":     forms.NumberInput(attrs={"class": "form-control", "placeholder": "100"}),
            "work_start":         forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "work_end":           forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "late_grace_minutes": forms.NumberInput(attrs={"class": "form-control", "placeholder": "15"}),
            "half_day_start":     forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "half_day_end":       forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "is_active":          forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "latitude":           "Decimal degrees. Right-click on Google Maps to copy.",
            "longitude":          "Decimal degrees. Right-click on Google Maps to copy.",
            "allowed_radius":     "Meters. Employees must be within this radius to check in.",
            "work_start":         "Office opening time. Check-in on or before this = Present.",
            "work_end":           "Office closing time. Used as default check-out if employee forgets.",
            "late_grace_minutes": "Minutes after work_start allowed before marking Late. e.g. 15 = 9:01 to 9:15 is Late.",
            "half_day_start":     "Half day window start time. e.g. 12:00 — check-in from here = Half Day.",
            "half_day_end":       "Half day window end time. e.g. 15:00 — check-in after this = Absent (too late).",
        }