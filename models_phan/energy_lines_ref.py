"""Shared XRF energy-line reference definitions."""

from __future__ import annotations

from typing import Iterable, List, Tuple

EnergyLine = Tuple[str, str, float]


# Canonical notation uses K_alpha/K_beta/L_alpha/L_beta.
ENERGY_LINES_CANONICAL: List[EnergyLine] = [
    ("Mg", "K_alpha", 1.2536), ("Mg", "K_beta", 1.302),
    ("Al", "K_alpha", 1.4867), ("Al", "K_beta", 1.550),
    ("Si", "K_alpha", 1.7400), ("Si", "K_beta", 1.836),
    ("P", "K_alpha", 2.0137), ("P", "K_beta", 2.139),
    ("S", "K_alpha", 2.3070), ("S", "K_beta", 2.464),
    ("Cl", "K_alpha", 2.6220), ("Cl", "K_beta", 2.815),
    ("K", "K_alpha", 3.3120), ("K", "K_beta", 3.590),
    ("Ca", "K_alpha", 3.6910), ("Ca", "K_beta", 4.012),
    ("Ti", "K_alpha", 4.5108), ("Ti", "K_beta", 4.9318),
    ("V", "K_alpha", 4.9520), ("V", "K_beta", 5.427),
    ("Cr", "K_alpha", 5.4150), ("Cr", "K_beta", 5.946),
    ("Mn", "K_alpha", 5.8988), ("Mn", "K_beta", 6.490),
    ("Fe", "K_alpha", 6.4038), ("Fe", "K_beta", 7.058),
    ("Co", "K_alpha", 6.9300), ("Co", "K_beta", 7.649),
    ("Ni", "K_alpha", 7.4780), ("Ni", "K_beta", 8.265),
    ("Cu", "K_alpha", 8.0480), ("Cu", "K_beta", 8.905),
    ("Zn", "K_alpha", 8.6389), ("Zn", "K_beta", 9.572),
    ("Ga", "K_alpha", 9.2510), ("Ga", "K_beta", 10.264),
    ("Ge", "K_alpha", 9.8860), ("Ge", "K_beta", 10.982),
    ("As", "K_alpha", 10.5430), ("As", "K_beta", 11.723),
    ("Se", "K_alpha", 11.2220), ("Se", "K_beta", 12.486),
    ("Br", "K_alpha", 11.9240), ("Br", "K_beta", 13.272),
    ("Rb", "K_alpha", 13.3950), ("Rb", "K_beta", 14.829),
    ("Sr", "K_alpha", 14.1650), ("Sr", "K_beta", 15.682),
    ("Y", "K_alpha", 14.9580), ("Y", "K_beta", 16.738),
    ("Zr", "K_alpha", 15.7750), ("Zr", "K_beta", 17.667),
    ("Nb", "K_alpha", 16.6150), ("Nb", "K_beta", 18.629),
    ("Mo", "K_alpha", 17.4790), ("Mo", "K_beta", 19.608),
    ("Ru", "K_alpha", 19.2780), ("Ru", "K_beta", 21.654),
    ("Rh", "K_alpha", 20.2160), ("Rh", "K_beta", 22.747),
    ("Pd", "K_alpha", 21.1740), ("Pd", "K_beta", 23.864),
    ("Ag", "K_alpha", 22.1630), ("Ag", "K_beta", 25.013),
    ("Cd", "K_alpha", 23.1730), ("Cd", "K_beta", 26.187),
    ("In", "K_alpha", 24.2080), ("In", "K_beta", 27.389),
    ("Sn", "K_alpha", 25.2710), ("Sn", "K_beta", 28.619),
    ("Sb", "K_alpha", 26.3590), ("Sb", "K_beta", 29.877),
    ("Te", "K_alpha", 27.4720),
    ("I", "K_alpha", 28.6120),
    ("Ba", "K_alpha", 29.7790),
    ("Zr", "L_alpha", 2.042), ("Zr", "L_beta", 2.307),
    ("Nb", "L_alpha", 2.166), ("Nb", "L_beta", 2.443),
    ("Mo", "L_alpha", 2.293), ("Mo", "L_beta", 2.629),
    ("Ru", "L_alpha", 2.558), ("Ru", "L_beta", 2.683),
    ("Rh", "L_alpha", 2.697), ("Rh", "L_beta", 2.834),
    ("Pd", "L_alpha", 2.839), ("Pd", "L_beta", 2.990),
    ("Ag", "L_alpha", 2.984), ("Ag", "L_beta", 3.150),
    ("Cd", "L_alpha", 3.133), ("Cd", "L_beta", 3.316),
    ("In", "L_alpha", 3.286), ("In", "L_beta", 3.487),
    ("Sn", "L_alpha", 3.444), ("Sn", "L_beta", 3.670),
    ("Sb", "L_alpha", 3.605), ("Sb", "L_beta", 3.843),
    ("Te", "L_alpha", 3.769), ("Te", "L_beta", 4.029),
    ("I", "L_alpha", 3.938), ("I", "L_beta", 4.220),
    ("Ba", "L_alpha", 4.466), ("Ba", "L_beta", 4.828),
    ("La", "L_alpha", 4.650), ("La", "L_beta", 5.043),
    ("Ce", "L_alpha", 4.840), ("Ce", "L_beta", 5.262),
    ("Pr", "L_alpha", 5.033), ("Pr", "L_beta", 5.489),
    ("Nd", "L_alpha", 5.230), ("Nd", "L_beta", 5.722),
    ("Sm", "L_alpha", 5.637), ("Sm", "L_beta", 6.180),
    ("Eu", "L_alpha", 5.846), ("Eu", "L_beta", 6.456),
    ("Gd", "L_alpha", 6.056), ("Gd", "L_beta", 6.713),
    ("Tb", "L_alpha", 6.273), ("Tb", "L_beta", 6.978),
    ("Dy", "L_alpha", 6.495), ("Dy", "L_beta", 7.247),
    ("Ho", "L_alpha", 6.719), ("Ho", "L_beta", 7.526),
    ("Er", "L_alpha", 6.949), ("Er", "L_beta", 7.810),
    ("Tm", "L_alpha", 7.180), ("Tm", "L_beta", 8.102),
    ("Yb", "L_alpha", 7.416), ("Yb", "L_beta", 8.401),
    ("Lu", "L_alpha", 7.655), ("Lu", "L_beta", 8.710),
    ("Hf", "L_alpha", 7.899), ("Hf", "L_beta", 9.022),
    ("Ta", "L_alpha", 8.146), ("Ta", "L_beta", 9.343),
    ("W", "L_alpha", 8.398), ("W", "L_beta", 9.673),
    ("Re", "L_alpha", 8.652), ("Re", "L_beta", 10.010),
    ("Os", "L_alpha", 8.911), ("Os", "L_beta", 10.355),
    ("Ir", "L_alpha", 9.175), ("Ir", "L_beta", 10.708),
    ("Pt", "L_alpha", 9.442), ("Pt", "L_beta", 11.072),
    ("Au", "L_alpha", 9.713), ("Au", "L_beta", 11.442),
    ("Hg", "L_alpha", 9.989), ("Hg", "L_beta", 11.822),
    ("Tl", "L_alpha", 10.269), ("Tl", "L_beta", 12.213),
    ("Pb", "L_alpha", 10.551), ("Pb", "L_beta", 12.614),
    ("Bi", "L_alpha", 10.839), ("Bi", "L_beta", 13.023),
]

_SHORT_LINE_MAP = {
    "K_alpha": "Ka",
    "K_beta": "Kb",
    "L_alpha": "La",
    "L_beta": "Lb",
}


def _to_short(lines: Iterable[EnergyLine]) -> List[EnergyLine]:
    return [(el, _SHORT_LINE_MAP.get(line_type, line_type), energy) for el, line_type, energy in lines]


def get_energy_lines(
    notation: str = "canonical",
    max_kev: float | None = None,
    sort_by_energy: bool = True,
) -> List[EnergyLine]:
    """
    Return shared energy lines with optional notation/energy filtering.

    notation: 'canonical' -> K_alpha/L_beta
              'short'     -> Ka/Lb
    """
    if notation not in {"canonical", "short"}:
        raise ValueError("notation must be one of {'canonical', 'short'}")

    lines = list(ENERGY_LINES_CANONICAL)
    if notation == "short":
        lines = _to_short(lines)
    if max_kev is not None:
        lines = [(el, lt, e) for el, lt, e in lines if e <= max_kev]
    if sort_by_energy:
        lines = sorted(lines, key=lambda x: x[2])
    return lines

