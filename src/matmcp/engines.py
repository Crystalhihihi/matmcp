"""Engine abstraction: one ScfResult contract, pluggable DFT backends.

Engines only *produce* standardized numbers (energies / fermi levels /
k-points / eigenvalues). All eigenvalue post-processing — band gap +
VBM/CBM analysis, DOS, band plots — lives here as engine-agnostic
functions, so GPAW and QE results go through byte-identical analysis.

Conventions:
- energies in eV, k-points in fractional reciprocal coordinates
- non-spin-polarized only (nspins == 1); engines raise otherwise
- every engine writes its heavy logs/stdout to files under the run dir,
  never to the MCP stdio channel
"""
from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt
from pathlib import Path
from typing import Protocol

import matplotlib
matplotlib.use("Agg")  # noqa: E402  (must precede pyplot import)
import matplotlib.pyplot as plt
import numpy as np
from ase.io import read as ase_read
from ase.optimize import BFGS

RY_PER_EV = 1.0 / 13.6056980659   # eV -> Ry (CODATA, QE convention)
FD_WIDTH_EV = 0.05                # Fermi-Dirac smearing, both engines
DOS_WIDTH_EV = 0.15               # gaussian DOS smearing (was hard-coded)
DOS_NPTS = 1000


# ------------------------------------------------------------- ScfResult

@dataclass
class ScfResult:
    """Standardized output of one scf / band-eigenvalue calculation."""
    energy_ev: float | None        # None for non-scf band calculations
    fermi_ev: float | None         # None if the engine printed none
    eigvals: np.ndarray            # (n_kpts, n_bands), absolute eV
    kpts_frac: np.ndarray          # (n_kpts, 3), fractional
    weights: np.ndarray            # (n_kpts,) k-point weights (DOS needs them)


class Engine(Protocol):
    """Backend contract. All methods write logs under out_dir, tagged."""
    name: str

    def relax(self, atoms, *, ecut_ev: float, kpts, out_dir: Path, tag: str,
              fmax: float, max_steps: int) -> dict:
        """-> {converged, n_steps, energy_ev, max_force_ev_per_a, atoms}"""
        ...

    def scf(self, atoms, *, ecut_ev: float, kpts, out_dir: Path,
            tag: str) -> ScfResult:
        ...

    def band_eigs(self, atoms, *, ecut_ev: float, kpts_scf, path,
                  out_dir: Path, tag: str) -> ScfResult:
        """Eigenvalues along an ase BandPath (non-selfconsistent)."""
        ...

    def realize_kpts(self, kpts) -> tuple[int, int, int]:
        """Map a requested grid to the grid this engine will actually run.
        Callers must record the realized grid — provenance honesty requires
        recorded parameters == executed parameters."""
        ...


# ------------------------------------------------- shared post-processing

_NAMED_KPTS = [((0, 0, 0), "Γ"), ((1/3, 1/3, 0), "K"), ((-1/3, -1/3, 0), "K"),
               ((1/3, -1/3, 0), "K'"), ((0.5, 0, 0), "M"), ((0, 0.5, 0), "M"),
               ((0.5, 0.5, 0), "M"), ((0, 0, 0.5), "A"), ((1/3, 1/3, 0.5), "H")]


def klabel(k) -> str:
    """Map fractional reciprocal coords to a named high-symmetry point."""
    for coords, name in _NAMED_KPTS:
        if np.allclose(k, coords, atol=0.06):
            return name
    return f"[{k[0]:.2f},{k[1]:.2f},{k[2]:.2f}]"


def gap_analysis(scf: ScfResult) -> dict:
    """Band gap + VBM/CBM positions from ibz eigenvalues (machine-derived).
    gap is None for metallic/gapless systems (callers pick their sentinel)."""
    evals, ef, kpts = scf.eigvals, scf.fermi_ev, scf.kpts_frac
    vb = np.where(evals < ef, evals, -np.inf)
    cb = np.where(evals > ef, evals, np.inf)
    if np.isfinite(vb).any() and np.isfinite(cb).any():
        ik_v, nb_v = np.unravel_index(vb.argmax(), vb.shape)
        ik_c, nb_c = np.unravel_index(cb.argmin(), cb.shape)
        gap = float(evals[ik_c, nb_c] - evals[ik_v, nb_v])
        vbm = {"k": kpts[ik_v].tolist(), "label": klabel(kpts[ik_v]),
               "band": int(nb_v), "energy_ev": round(float(evals[ik_v, nb_v]), 4)}
        cbm = {"k": kpts[ik_c].tolist(), "label": klabel(kpts[ik_c]),
               "band": int(nb_c), "energy_ev": round(float(evals[ik_c, nb_c]), 4)}
        gap_type = "direct" if ik_v == ik_c else "indirect"
    else:
        gap, vbm, cbm, gap_type = None, None, None, "metallic"
    return {"gap": gap, "vbm": vbm, "cbm": cbm, "gap_type": gap_type}


def dos_arrays(scf: ScfResult, width: float = DOS_WIDTH_EV,
               npts: int = DOS_NPTS) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian-smeared DOS, energies already relative to the Fermi level.
    Replicates ase.dft.dos.DOS(calc, npts, width).get_dos() for nspins=1:
    dos(E) = 2 * sum_k w_k sum_n exp(-((E-e_kn)/width)^2) / (sqrt(pi)*width).
    NOTE: the old inline code subtracted ef from an already fermi-relative
    grid (double shift); this layer defines the single correct convention."""
    e = scf.eigvals - scf.fermi_ev
    energies = np.linspace(e.min() - 5 * width, e.max() + 5 * width, npts)
    dos = np.zeros(npts)
    for w, e_n in zip(scf.weights, e):
        x = -((energies[:, None] - e_n[None, :]) / width) ** 2
        dos += w * np.exp(x).sum(axis=1) / (sqrt(pi) * width)
    dos *= 2  # unpolarized: both spin channels
    return energies, dos


def plot_dos(scf: ScfResult, png: Path, window_ev: float) -> None:
    e, d = dos_arrays(scf)
    mask = (e > -window_ev) & (e < window_ev)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(e[mask], d[mask], color="darkgreen")
    ax.axvline(0, ls=":", c="k", lw=1)
    ax.set_xlabel("E - E$_F$ (eV)")
    ax.set_ylabel("DOS (states/eV)")
    fig.tight_layout()
    fig.savefig(png, dpi=120)
    plt.close(fig)


def plot_bands(band: ScfResult, path, fermi_ev: float, png: Path,
               window_ev: float) -> None:
    """Band plot along path; energies referenced to the *scf* Fermi level
    (ASE itself warns a band calculation's own Fermi level may be off)."""
    from ase.spectrum.band_structure import BandStructure
    bs = BandStructure(path=path, energies=band.eigvals[None, :, :],
                       reference=fermi_ev)
    bs.plot(filename=str(png), emax=window_ev, emin=-window_ev)


# ------------------------------------------------------------- GPAW engine

class GpawEngine:
    """GPAW plane-wave backend. Physics transplanted verbatim from the old
    workflows.py: PW(ecut), PBE, FermiDirac(0.05), Gamma-centered k-grid,
    ASE BFGS relax, gpw restart + fixed_density for bands."""
    name = "gpaw-pw"

    def realize_kpts(self, kpts):
        # GPAW gamma=True is Gamma-centered for any parity: run as requested.
        return tuple(int(n) for n in kpts)

    @staticmethod
    def _calc(ecut_ev: float, kpts, txt: Path):
        # gamma=True: force a Gamma-centered grid. GPAW's default Monkhorst-Pack
        # offsets even-n grids, which then MISS K=(1/3,1/3,0) on hexagonal cells.
        from gpaw import FermiDirac, GPAW, PW
        return GPAW(mode=PW(ecut_ev), xc="PBE",
                    kpts={"size": tuple(kpts), "gamma": True},
                    occupations=FermiDirac(FD_WIDTH_EV), txt=str(txt))

    def relax(self, atoms, *, ecut_ev, kpts, out_dir, tag, fmax, max_steps):
        out_dir = Path(out_dir)
        atoms = atoms.copy()
        atoms.calc = self._calc(ecut_ev, kpts, out_dir / f"{tag}.txt")
        opt = BFGS(atoms, trajectory=str(out_dir / f"{tag}.traj"),
                   logfile=str(out_dir / f"{tag}.log"))
        opt.run(fmax=fmax, steps=max_steps)
        forces = atoms.get_forces()
        return {"converged": bool(opt.converged()),
                "n_steps": opt.get_number_of_steps(),
                "energy_ev": float(atoms.get_potential_energy()),
                "max_force_ev_per_a": float(np.linalg.norm(forces, axis=1).max()),
                "atoms": atoms}

    def scf(self, atoms, *, ecut_ev, kpts, out_dir, tag):
        out_dir = Path(out_dir)
        atoms = atoms.copy()
        atoms.calc = self._calc(ecut_ev, kpts, out_dir / f"{tag}.txt")
        energy = float(atoms.get_potential_energy())
        atoms.calc.write(str(out_dir / "gs.gpw"))  # restart for band_eigs
        calc = atoms.calc
        ef = float(calc.get_fermi_level())
        kpts_ibz = calc.get_ibz_k_points()
        evals = np.array([calc.get_eigenvalues(kpt=k)
                          for k in range(len(kpts_ibz))])
        return ScfResult(energy, ef, evals, np.asarray(kpts_ibz),
                         np.asarray(calc.get_k_point_weights()))

    def band_eigs(self, atoms, *, ecut_ev, kpts_scf, path, out_dir, tag):
        from gpaw import GPAW
        gpw = Path(out_dir) / "gs.gpw"
        calc = GPAW(str(gpw)).fixed_density(kpts=path, symmetry="off")
        n = len(path.kpts)
        evals = np.array([calc.get_eigenvalues(kpt=k) for k in range(n)])
        return ScfResult(None, float(calc.get_fermi_level()), evals,
                         np.asarray(path.kpts), np.full(n, 1.0 / n))


# ---------------------------------------------------------------- QE engine

# Pseudopotential map: element -> file in QE_PSEUDO_DIR
# (pslibrary PBE kjpaw set, inventoried 2026-08).
QE_PSEUDO_DIR = Path.home() / "qe-pseudo" / "pslibrary"
QE_PSEUDOS = {
    "H": "H.pbe-kjpaw_psl.1.0.0.UPF",
    "Li": "Li.pbe-s-kjpaw_psl.1.0.0.UPF",
    "O": "O.pbe-n-kjpaw_psl.1.0.0.UPF",
    "S": "S.pbe-n-kjpaw_psl.1.0.0.UPF",
    "Si": "Si.pbe-n-kjpaw_psl.1.0.0.UPF",
    "Ti": "Ti.pbe-spn-kjpaw_psl.1.0.0.UPF",
    "Ga": "Ga.pbe-dn-kjpaw_psl.1.0.0.UPF",
    "As": "As.pbe-n-kjpaw_psl.1.0.0.UPF",
    "Mo": "Mo.pbe-spn-kjpaw_psl.1.0.0.UPF",
}


class QeEngine:
    """Quantum ESPRESSO pw.x backend via ase.calculators.espresso.

    Parameter parity with GpawEngine: ecut_ev converted to Ry for ecutwfc
    (ecutrho = 4x for the kjpaw PAW set), Fermi-Dirac smearing 0.05 eV
    (degauss in Ry). k-grids go through realize_kpts(): ASE's gamma=True
    only Gamma-centers ODD sizes, so even sizes are rounded up first
    (multiples of 3 -> next odd multiple of 3, preserving hex K points).
    pw.x stdout/stderr are redirected to <tag dir>/espresso.pwo|.err by ASE.
    """
    name = "qe-pw"

    def realize_kpts(self, kpts):
        # ASE gamma=True keeps a grid Gamma-centered only for ODD sizes —
        # kpts2sizeandoffsets gives even sizes a half-step shift that misses
        # Gamma AND K (E11 evidence: QE 6x6/12x12 on hex MoS2 gave gap
        # 1.99/1.78 eV "indirect"; 3/9/15 give the correct ~1.67 direct).
        # Rule: round up to odd; a multiple of 3 rounds to the next ODD
        # multiple of 3 (n+3) so K=(1/3,1/3,0) stays in the grid on hex axes.
        out = []
        for n in kpts:
            n = int(n)
            if n % 2 == 1:
                out.append(n)
            elif n % 3 == 0:
                out.append(n + 3)
            else:
                out.append(n + 1)
        return tuple(out)

    def __init__(self, pseudo_dir: str | Path | None = None, command: str | None = None):
        from ase.calculators.espresso import EspressoProfile
        self.pseudo_dir = Path(pseudo_dir) if pseudo_dir else QE_PSEUDO_DIR
        # MATMCP_QE_COMMAND overrides the pw.x binary (the Ubuntu 6.7 build
        # crashes reading any UPF — md5_from_file fortify abort; a fixed
        # pw.x 7.x can be pointed at without touching code).
        if command is None:
            import os
            command = os.environ.get("MATMCP_QE_COMMAND", "pw.x")
        self.profile = EspressoProfile(command=command,
                                       pseudo_dir=str(self.pseudo_dir))

    # ---- helpers

    def _pseudos(self, atoms) -> dict:
        out, missing = {}, []
        for sym in sorted(set(atoms.get_chemical_symbols())):
            fn = QE_PSEUDOS.get(sym)
            if fn is not None and (self.pseudo_dir / fn).exists():
                out[sym] = fn
            else:
                missing.append(sym)
        if missing:
            raise ValueError(
                f"no QE pseudopotential for {missing} in {self.pseudo_dir} "
                f"(known: {sorted(QE_PSEUDOS)})")
        return out

    def _espresso(self, atoms, ecut_ev, calculation, out_dir, tag, kpts,
                  tprnfor=False):
        from ase.calculators.espresso import Espresso
        ecutwfc_ry = ecut_ev * RY_PER_EV
        control = {"calculation": calculation, "verbosity": "high",
                   "prefix": "pwscf",
                   # shared wf/density area so scf -> bands handoff works
                   "outdir": str(Path(out_dir) / "qe_wf")}
        if tprnfor:
            control["tprnfor"] = True
        input_data = {
            "control": control,
            "system": {"ecutwfc": ecutwfc_ry,
                       "ecutrho": 4.0 * ecutwfc_ry,
                       "occupations": "smearing",
                       "smearing": "fd",  # Fermi-Dirac, = GPAW FermiDirac(0.05)
                       "degauss": FD_WIDTH_EV * RY_PER_EV},
            "electrons": {},
        }
        return Espresso(profile=self.profile,
                        directory=str(Path(out_dir) / f"qe_{tag}"),
                        input_data=input_data,
                        pseudopotentials=self._pseudos(atoms), kpts=kpts)

    @staticmethod
    def _parse_pwo(calc) -> ScfResult:
        """Re-read espresso.pwo into a SinglePointDFTCalculator and standardize.
        (ASE's GenericFileIOCalculator drops eigenvalues/fermi from results;
        the .pwo parser keeps them, so we go straight to the file.)"""
        out = ase_read(str(calc.directory / calc.template.outputname),
                       format="espresso-out")
        sp = out.calc
        kpts_ibz = np.asarray(sp.get_ibz_k_points())
        evals = np.array([sp.get_eigenvalues(kpt=k)
                          for k in range(len(kpts_ibz))])
        if sp.get_number_of_spins() != 1:
            raise NotImplementedError("spin-polarized QE runs not supported")
        ef = sp.get_fermi_level()
        energy = sp.results.get("energy")
        return ScfResult(None if energy is None else float(energy),
                         None if ef is None else float(ef),
                         evals, kpts_ibz, np.asarray(sp.get_k_point_weights()))

    # ---- Engine API

    def relax(self, atoms, *, ecut_ev, kpts, out_dir, tag, fmax, max_steps):
        out_dir = Path(out_dir)
        atoms = atoms.copy()
        atoms.calc = self._espresso(atoms, ecut_ev, "scf", out_dir, tag,
                                    {"size": tuple(kpts), "gamma": True},
                                    tprnfor=True)
        opt = BFGS(atoms, trajectory=str(out_dir / f"{tag}.traj"),
                   logfile=str(out_dir / f"{tag}.log"))
        opt.run(fmax=fmax, steps=max_steps)
        forces = atoms.get_forces()
        return {"converged": bool(opt.converged()),
                "n_steps": opt.get_number_of_steps(),
                "energy_ev": float(atoms.get_potential_energy()),
                "max_force_ev_per_a": float(np.linalg.norm(forces, axis=1).max()),
                "atoms": atoms}

    def scf(self, atoms, *, ecut_ev, kpts, out_dir, tag):
        calc = self._espresso(atoms, ecut_ev, "scf", out_dir, tag,
                              {"size": tuple(kpts), "gamma": True})
        atoms = atoms.copy()
        atoms.calc = calc
        calc.calculate(atoms, ["energy"], ["all"])
        return self._parse_pwo(calc)

    def band_eigs(self, atoms, *, ecut_ev, kpts_scf, path, out_dir, tag):
        calc = self._espresso(atoms, ecut_ev, "bands", out_dir, tag, kpts=path)
        atoms = atoms.copy()
        atoms.calc = calc
        calc.calculate(atoms, ["energy"], ["all"])
        res = self._parse_pwo(calc)
        res.energy_ev = None  # a 'bands' run has no total energy
        return res


# -------------------------------------------------------------- registry

def get_engine(name: str) -> Engine:
    """Engine instance by name: 'gpaw' (default) or 'qe'."""
    key = (name or "gpaw").lower()
    if key in ("gpaw", "gpaw-pw"):
        return GpawEngine()
    if key in ("qe", "qe-pw", "espresso", "quantum-espresso"):
        return QeEngine()
    raise ValueError(f"unknown engine {name!r} — choose 'gpaw' or 'qe'")
