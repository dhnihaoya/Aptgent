from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from aptgent.domain.models import TargetMolecule

_log = logging.getLogger(__name__)


def _check_rdkit() -> bool:
    try:
        from rdkit import Chem  # noqa: F401
        return True
    except Exception:
        return False


def _silence_rdkit() -> None:
    """Suppress RDKit's stderr warnings (e.g. SMILES parse errors)."""
    try:
        from rdkit import RDLogger
        RDLogger.DisableLog("rdApp.*")
    except Exception:
        pass


class SimpleMoleculeResolver:
    """Lightweight resolver using RDKit + PubChem PUG REST."""

    def __init__(self) -> None:
        self.has_rdkit = _check_rdkit()
        if self.has_rdkit:
            _silence_rdkit()
        self._last_lookup_error: str | None = None

    def _validate_smiles(self, smiles: str) -> bool:
        if not self.has_rdkit:
            # Cannot validate without RDKit; use minimal heuristic to avoid
            # treating plain molecule names (e.g. "theophylline", "茶碱")
            # as SMILES.
            if not smiles:
                return False
            # Reject non-ASCII strings (e.g. CJK names)
            if any(ord(ch) > 127 for ch in smiles):
                return False
            # Reject long all-alphabetic strings — they are almost certainly
            # names, not SMILES. Short ones like "C" or "CCO" are allowed.
            if len(smiles) > 6 and smiles.isalpha():
                return False
            return True
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        return mol is not None

    def _pubchem_name_to_smiles(self, name: str, retries: int = 2) -> str | None:
        encoded = urllib.parse.quote(name)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/property/IsomericSMILES/JSON"
        self._last_lookup_error = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                props = data.get("PropertyTable", {}).get("Properties", [])
                if props:
                    return props[0].get("IsomericSMILES") or props[0].get("SMILES")
                _log.warning("PubChem returned no properties for '%s'", name)
                self._last_lookup_error = "not_found"
                return None
            except Exception as exc:
                _log.warning(
                    "PubChem lookup failed for '%s' (attempt %d/%d): %s",
                    name, attempt + 1, retries + 1, exc,
                )
                self._last_lookup_error = "network"
                if attempt < retries:
                    time.sleep(1 + attempt)
        return None

    def resolve(self, input_text: str) -> TargetMolecule:
        candidate = TargetMolecule(input_text=input_text.strip())
        text = candidate.input_text

        # 1. Try as SMILES first
        if self._validate_smiles(text):
            candidate.smiles = text
            candidate.resolved_name = text
            candidate.resolution_status = "resolved"
            return candidate

        # 2. Try PubChem name lookup
        smiles = self._pubchem_name_to_smiles(text)
        if smiles and self._validate_smiles(smiles):
            candidate.smiles = smiles
            candidate.resolved_name = text
            candidate.resolution_status = "resolved"
            return candidate

        # 3. Fallback: needs confirmation / manual input
        candidate.resolution_status = "failed"
        candidate.error_detail = self._last_lookup_error
        return candidate
