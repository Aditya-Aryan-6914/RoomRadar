from django import forms

from .models import Override, Room


class UploadForm(forms.Form):
    department = forms.CharField(max_length=100, help_text="e.g. Computer Engineering (created if new)")
    class_name = forms.CharField(max_length=60, required=False,
                                 help_text="e.g. SE-A. Leave blank to auto-detect from the PDF.")
    room = forms.CharField(max_length=60, required=False,
                           help_text="Home room of this class, e.g. Room 101. Blank = auto-detect.")
    pdf = forms.FileField()

    def clean_pdf(self):
        f = self.cleaned_data["pdf"]
        if not f.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Please upload a .pdf file.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("PDF is larger than 10 MB.")
        return f


class OverrideForm(forms.ModelForm):
    class Meta:
        model = Override
        fields = ["room", "kind", "date", "start_time", "end_time", "title", "teacher", "reason"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean(self):
        data = super().clean()
        s, e = data.get("start_time"), data.get("end_time")
        if s and e and e <= s:
            raise forms.ValidationError("End time must be after start time.")
        return data


class QuickOccupyForm(forms.Form):
    room = forms.ModelChoiceField(Room.objects.select_related("department"))
    minutes = forms.IntegerField(min_value=5, max_value=720, initial=60, label="For (minutes)")
    reason = forms.CharField(max_length=200, required=False, initial="Emergency")
