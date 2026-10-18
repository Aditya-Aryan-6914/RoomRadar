import re
from datetime import date

from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify

from .models import Institute, Override, Room, StudentProfile

User = get_user_model()

# A student may hold a lab for at most this long in a single booking.
MAX_STUDENT_LAB_MINUTES = 120


class InstituteSignupForm(UserCreationForm):
    institute_name = forms.CharField(max_length=150, label="College / institute name")
    city = forms.CharField(max_length=80, required=False)
    email = forms.EmailField(required=False)
    institute_password = forms.CharField(
        label="Institute password", min_length=6, widget=forms.PasswordInput(render_value=False),
        help_text="Students need this to join your institute. You can change it later.")
    institute_password2 = forms.CharField(label="Confirm institute password",
                                          widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = User
        fields = ("institute_name", "city", "username", "email", "password1", "password2",
                  "institute_password", "institute_password2")

    def clean(self):
        data = super().clean()
        if data.get("institute_password") and data["institute_password"] != data.get("institute_password2"):
            self.add_error("institute_password2", "The two institute passwords do not match.")
        return data

    def clean_institute_name(self):
        name = self.cleaned_data["institute_name"].strip()
        if not slugify(name):
            raise forms.ValidationError("Please use letters or numbers in the name.")
        return name

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get("email", "")
        user.save()
        base = slugify(self.cleaned_data["institute_name"])[:50]
        slug, n = base, 2
        while Institute.objects.filter(slug=slug).exists():
            slug, n = f"{base}-{n}", n + 1
        inst = Institute(owner=user, name=self.cleaned_data["institute_name"], slug=slug,
                         city=self.cleaned_data.get("city", ""))
        inst.set_access_password(self.cleaned_data["institute_password"])
        inst.save()
        return inst


PRN_RE = re.compile(r"^[A-Za-z0-9_-]{3,30}$")


def student_username(inst, prn):
    return f"{inst.slug}__{prn.lower()}"


class StudentSignupForm(forms.Form):
    institute = forms.ModelChoiceField(Institute.objects.all(), empty_label="Select your institute")
    full_name = forms.CharField(max_length=120)
    prn = forms.CharField(max_length=30, label="PRN / ID number")
    institute_password = forms.CharField(label="Institute password", widget=forms.PasswordInput,
                                         help_text="Ask your college for this password.")
    password1 = forms.CharField(label="Create your password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm your password", widget=forms.PasswordInput)

    def clean_prn(self):
        prn = self.cleaned_data["prn"].strip().upper()
        if not PRN_RE.match(prn):
            raise forms.ValidationError("Use 3-30 letters, numbers, - or _ only.")
        return prn

    def clean(self):
        data = super().clean()
        inst, prn = data.get("institute"), data.get("prn")
        if inst and data.get("institute_password") is not None:
            if not inst.check_access_password(data["institute_password"]):
                self.add_error("institute_password", "Wrong institute password.")
        if inst and prn and StudentProfile.objects.filter(institute=inst, prn=prn).exists():
            self.add_error("prn", "This PRN / ID is already registered. Please log in.")
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            try:
                validate_password(p1)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data

    def save(self):
        d = self.cleaned_data
        user = User.objects.create_user(username=student_username(d["institute"], d["prn"]),
                                        password=d["password1"], first_name=d["full_name"][:150])
        return StudentProfile.objects.create(user=user, institute=d["institute"],
                                             full_name=d["full_name"], prn=d["prn"])


class StudentLoginForm(forms.Form):
    institute = forms.ModelChoiceField(Institute.objects.all(), empty_label="Select your institute")
    prn = forms.CharField(max_length=30, label="PRN / ID number")
    password = forms.CharField(widget=forms.PasswordInput)

    def clean(self):
        data = super().clean()
        if data.get("institute") and data.get("prn") and data.get("password"):
            user = authenticate(username=student_username(data["institute"], data["prn"].strip()),
                                password=data["password"])
            if not user or not hasattr(user, "student_profile"):
                raise forms.ValidationError("Wrong PRN / ID or password for this institute.")
            data["user"] = user
        return data


class InstitutePasswordForm(forms.Form):
    password1 = forms.CharField(label="New institute password", min_length=6, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm new password", widget=forms.PasswordInput)

    def clean(self):
        data = super().clean()
        if data.get("password1") and data["password1"] != data.get("password2"):
            self.add_error("password2", "The two passwords do not match.")
        return data


class UnlockForm(forms.Form):
    password = forms.CharField(label="Institute password", widget=forms.PasswordInput)


class UploadForm(forms.Form):
    department = forms.CharField(
        max_length=100, required=False,
        help_text="Optional. Read from the PDF title (e.g. 'AIML - Time Table'). Fill only if it is not detected.")
    pdf = forms.FileField(label="Timetable PDF")

    def clean_pdf(self):
        f = self.cleaned_data["pdf"]
        if not f.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Please upload a .pdf file.")
        if f.size > 15 * 1024 * 1024:
            raise forms.ValidationError("PDF is larger than 15 MB.")
        return f


class _TimeRangeMixin:
    def clean(self):
        data = super().clean()
        s, e = data.get("start_time"), data.get("end_time")
        if s and e and e <= s:
            raise forms.ValidationError("End time must be after start time.")
        return data


class RoomChoiceForm(forms.Form):
    def __init__(self, *a, institute=None, user=None, **kw):
        super().__init__(*a, **kw)
        self.user = user
        qs = Room.objects.filter(department__institute=institute).select_related("department")
        self.fields["room"].queryset = qs


class OverrideForm(_TimeRangeMixin, RoomChoiceForm):
    room = forms.ModelChoiceField(Room.objects.none())
    kind = forms.ChoiceField(choices=[k for k in Override.KINDS if k[0] != Override.BOOKING])
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    title = forms.CharField(max_length=150, required=False, label="Subject / event")
    teacher = forms.CharField(max_length=100, required=False)
    reason = forms.CharField(max_length=200, required=False)


class QuickOccupyForm(RoomChoiceForm):
    room = forms.ModelChoiceField(Room.objects.none())
    minutes = forms.IntegerField(min_value=5, max_value=720, initial=60, label="For (minutes)")
    reason = forms.CharField(max_length=200, required=False, initial="Emergency")


class BookingForm(_TimeRangeMixin, RoomChoiceForm):
    room = forms.ModelChoiceField(Room.objects.none())
    role = forms.ChoiceField(choices=Override.ROLES, initial="student", label="I am a")
    teacher = forms.CharField(max_length=100, label="Your name")
    title = forms.CharField(max_length=150, label="Purpose", help_text="e.g. Group discussion, project work, extra lecture")
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}))

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d < date.today():
            raise forms.ValidationError("Pick today or a future date.")
        return d

    def _is_student(self, role):
        """Students are real student accounts, or anyone booking as a student."""
        return role == "student" or hasattr(self.user, "student_profile")

    def clean(self):
        data = super().clean()
        room, s, e = data.get("room"), data.get("start_time"), data.get("end_time")
        if room and s and e and e > s and room.room_type == Room.LAB \
                and self._is_student(data.get("role")):
            minutes = (e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)
            if minutes > MAX_STUDENT_LAB_MINUTES:
                raise forms.ValidationError(
                    f"Students can book a lab for at most {MAX_STUDENT_LAB_MINUTES // 60} hours "
                    f"at a time. You asked for {minutes // 60}h {minutes % 60:02d}m.")
        return data