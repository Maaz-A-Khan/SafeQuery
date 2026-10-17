from django import forms


class ConnectForm(forms.Form):
    name = forms.CharField(max_length=100, help_text='A label, e.g. "Chinook (Postgres)".')
    url = forms.CharField(
        label="Connection string",
        widget=forms.PasswordInput(render_value=True),
        help_text="postgresql+psycopg://user:pass@host:5432/db, mysql+pymysql://..., or sqlite:///path/to/file.db",
    )


class AskForm(forms.Form):
    question = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
