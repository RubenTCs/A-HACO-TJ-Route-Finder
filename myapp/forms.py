from django import forms

class RouteForm(forms.Form):
    halte_asal = forms.CharField(label="Halte Asal", max_length=100)
    halte_tujuan = forms.CharField(label="Halte Tujuan", max_length=100)
    preferensi = forms.ChoiceField(
        choices=[
            ("seimbang", "Seimbang"),
            ("min_transit", "Minimal Transit"),
            ("cepat", "Tercepat"),
            ("murah", "Termurah"),
        ],
        label="Preferensi Rute",
        initial="seimbang"
    )
    jam_berangkat = forms.TimeField(label="Jam Berangkat", input_formats=["%H:%M"])
    tanggal_berangkat = forms.DateField(label="Tanggal Berangkat", input_formats=["%Y-%m-%d"])
    metode_solver = forms.ChoiceField(
        choices=[
            ("MILP", "MILP (Gurobi))"),
            ("ASTAR", "A* (A-Star)"),
            ("HACO", "Hybrid Ant Colony Optimization (HACO)")
        ],
        label="Metode Solver",
        initial="MILP"
    )