from enum import Enum


class Step(str, Enum):
    INTAKE = "intake"
    SECONDARY_STRUCTURE = "secondary_structure"
    SITE_PROPOSAL = "site_proposal"
    CANDIDATE_ENUMERATION = "candidate_enumeration"
    PRIMARY_SCORING = "primary_scoring"
    SPECIFICITY_FILTER = "specificity_filter"
    DOCKING_SELECTION = "docking_selection"
    DOCKING_RUN = "docking_run"
    SPATIAL_RANK = "spatial_rank"
    FINAL_REPORT = "final_report"


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
