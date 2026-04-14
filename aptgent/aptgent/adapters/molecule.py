from __future__ import annotations

import json
import urllib.parse
import urllib.request

from aptgent.domain.models import TargetMolecule


def _check_rdkit() -> bool:
    try:
        from rdkit import Chem  # noqa: F401
        return True
    except Exception:
        return False


class SimpleMoleculeResolver:
    """Lightweight resolver using RDKit + PubChem PUG REST."""

    def __init__(self) -> None:
        self.has_rdkit = _check_rdkit()

    def _validate_smiles(self, smiles: str) -> bool:
        if not self.has_rdkit:
            # Cannot validate without RDKit; assume valid if it looks like SMILES
            return len(smiles) > 0
        from rdkit import Chem

        mol = Chem.MolFromSmiles(smiles)
        return mol is not None

    def _pubchem_name_to_smiles(self, name: str) -> str | None:
        try:
            encoded = urllib.parse.quote(name)
            url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded}/property/IsomericSMILES/JSON"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            props = data.get("PropertyTable", {}).get("Properties", [])
            if props:
                return props[0].get("IsomericSMILES") or props[0].get("SMILES")
        except Exception:
            return None
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
        return candidate
