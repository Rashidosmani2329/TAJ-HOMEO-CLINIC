from kivy.app import App
from kivy.lang import Builder
from kivy.properties import ListProperty, StringProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
import csv
import os

KV = """
<HomeoRoot>:
    orientation: 'vertical'
    padding: 8
    spacing: 8

    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        TextInput:
            id: search_input
            multiline: False
            hint_text: 'Search by name or mobile'
            on_text: root.filter(search_input.text)
        Button:
            text: 'Add'
            size_hint_x: None
            width: '90dp'
            on_release: root.open_add()

    RecycleView:
        id: rv
        viewclass: 'PatientRow'
        data: root.rv_data

<PatientRow@BoxLayout>:
    orientation: 'horizontal'
    size_hint_y: None
    height: '48dp'
    padding: 8
    spacing: 8
    Label:
        text: root.title
        size_hint_x: None
        width: '60dp'
    Label:
        text: root.name
    Label:
        text: root.age
        size_hint_x: None
        width: '50dp'
    Label:
        text: root.mobile
        size_hint_x: None
        width: '110dp'
    Button:
        text: 'Edit'
        size_hint_x: None
        width: '70dp'
        on_release: app.root.open_edit(root.index)

<PatientForm>:
    orientation: 'vertical'
    spacing: 8
    padding: 8
    TextInput:
        id: title
        multiline: False
        hint_text: 'Title (e.g. MR)'
    TextInput:
        id: name
        multiline: False
        hint_text: 'Full name'
    TextInput:
        id: age
        multiline: False
        hint_text: 'Age'
        input_filter: 'int'
    TextInput:
        id: mobile
        multiline: False
        hint_text: 'Mobile number'
    TextInput:
        id: address
        hint_text: 'Address'
    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        Button:
            text: 'Save'
            on_release: root.on_save()
        Button:
            text: 'Cancel'
            on_release: root.on_cancel()
"""


class HomeoRoot(BoxLayout):
    rv_data = ListProperty([])
    patients = ListProperty([])
    data_file = StringProperty('patients.csv')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.load_patients()

    def data_dir(self):
        try:
            appdata = os.getenv('APPDATA') or os.path.expanduser('~')
            storage = os.path.join(appdata, 'TajHomeo')
            os.makedirs(storage, exist_ok=True)
            return storage
        except Exception:
            return os.path.dirname(__file__)

    def patients_path(self):
        return os.path.join(self.data_dir(), self.data_file)

    def load_patients(self):
        path = self.patients_path()
        self.patients = []
        if os.path.exists(path):
            try:
                with open(path, newline='', encoding='utf-8') as f:
                    rdr = csv.DictReader(f)
                    for row in rdr:
                        self.patients.append(row)
            except Exception:
                pass
        self.refresh_view()

    def save_patients(self):
        path = self.patients_path()
        fieldnames = ['Title', 'Name', 'Age', 'Mobile', 'Address']
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for p in self.patients:
                    w.writerow({k: p.get(k, '') for k in fieldnames})
        except Exception:
            pass
        self.refresh_view()

    def refresh_view(self, filtered=None):
        src = filtered if filtered is not None else self.patients
        self.rv_data = []
        for i, p in enumerate(src):
            self.rv_data.append({'title': p.get('Title',''), 'name': p.get('Name',''), 'age': p.get('Age',''), 'mobile': p.get('Mobile',''), 'index': i})

    def filter(self, text):
        t = (text or '').strip().lower()
        if not t:
            self.refresh_view()
            return
        out = []
        for p in self.patients:
            if t in (p.get('Name','').lower()) or t in (p.get('Mobile','').lower()):
                out.append(p)
        self.refresh_view(out)

    def open_add(self):
        form = PatientForm(on_save=self._add_patient, on_cancel=lambda: popup.dismiss())
        popup = Popup(title='Add Patient', content=form, size_hint=(.9, .9))
        form._popup = popup
        popup.open()

    def _add_patient(self, data):
        self.patients.append({'Title': data.get('Title',''), 'Name': data.get('Name',''), 'Age': data.get('Age',''), 'Mobile': data.get('Mobile',''), 'Address': data.get('Address','')})
        self.save_patients()

    def open_edit(self, index):
        try:
            idx = int(index)
            p = self.patients[idx]
        except Exception:
            return
        def on_save(data):
            self.patients[idx] = {'Title': data.get('Title',''), 'Name': data.get('Name',''), 'Age': data.get('Age',''), 'Mobile': data.get('Mobile',''), 'Address': data.get('Address','')}
            self.save_patients()
            popup.dismiss()
        form = PatientForm(on_save=on_save, on_cancel=lambda: popup.dismiss())
        form.ids.title.text = p.get('Title','')
        form.ids.name.text = p.get('Name','')
        form.ids.age.text = p.get('Age','')
        form.ids.mobile.text = p.get('Mobile','')
        form.ids.address.text = p.get('Address','')
        popup = Popup(title='Edit Patient', content=form, size_hint=(.9, .9))
        form._popup = popup
        popup.open()


class PatientForm(BoxLayout):
    on_save = ObjectProperty(None)
    on_cancel = ObjectProperty(None)

    def on_save(self):
        # provided by instantiation
        pass

    def on_cancel(self):
        if hasattr(self, '_popup'):
            self._popup.dismiss()

    def on_save(self):
        data = {
            'Title': self.ids.title.text.strip(),
            'Name': self.ids.name.text.strip(),
            'Age': self.ids.age.text.strip(),
            'Mobile': self.ids.mobile.text.strip(),
            'Address': self.ids.address.text.strip(),
        }
        cb = getattr(self, 'on_save', None)
        if callable(cb):
            cb(data)
        if hasattr(self, '_popup'):
            self._popup.dismiss()


class HomeoApp(App):
    def build(self):
        Builder.load_string(KV)
        return HomeoRoot()


if __name__ == '__main__':
    HomeoApp().run()
