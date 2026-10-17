from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.text import slugify

from .models import Institute, Override, Room

User = get_user_model()


class InstituteSignupForm(UserCreationForm):
    institute_name = forms.CharField(max_length=150, label="College / institute name")
    city = forms.CharField(max_length=80, required=False)
    email = forms.EmailField(required=False)

    class Meta:
        model = User
        fields = ("institute_name", "city", "username", "email", "password1", "password2")

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
        return Institute.objects.create(owner=user, name=self.cleaned_data["institute_name"],
                                        slug=slug, city=self.cleaned_data.get("city", ""))


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
    def __init__(self, *a, institute=None, **kw):
        super().__init__(*a, **kw)
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
