"""Validated data contracts for visual learning documents."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DOCUMENT_TYPES = {"overview", "full_note", "diagram"}
THEME_IDS = {
    "study-notes",
    "clean-lecture",
    "chalkboard",
    "technical-blueprint",
}
DIAGRAM_TYPES = {
    "auto",
    "concept_chain",
    "process_flow",
    "comparison",
    "paired_contrast",
    "signal_flow",
    "decision_axis",
    "hierarchy",
    "timeline",
    "mind_map",
}

DocumentType = Literal["overview", "full_note", "diagram"]
ThemeId = Literal[
    "study-notes",
    "clean-lecture",
    "chalkboard",
    "technical-blueprint",
]
DiagramType = Literal[
    "auto",
    "concept_chain",
    "process_flow",
    "comparison",
    "paired_contrast",
    "signal_flow",
    "decision_axis",
    "hierarchy",
    "timeline",
    "mind_map",
]
RenderedDiagramType = Literal[
    "concept_chain",
    "process_flow",
    "comparison",
    "paired_contrast",
    "signal_flow",
    "decision_axis",
    "hierarchy",
    "timeline",
    "mind_map",
]
ShortText = Annotated[str, Field(min_length=1, max_length=40)]
SignalText = Annotated[str, Field(min_length=1, max_length=120)]
DescriptionText = Annotated[str, Field(min_length=1, max_length=240)]
Identifier = Annotated[str, Field(min_length=1, max_length=160)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    id: Identifier
    owner_type: Literal["study", "collection"]
    owner_id: Identifier
    excerpt: Annotated[str, Field(min_length=1, max_length=500)]
    line_id: Optional[Identifier] = None
    paragraph_index: Optional[int] = Field(default=None, ge=0)
    start_seconds: Optional[float] = Field(default=None, ge=0)
    end_seconds: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_range(self) -> "SourceReference":
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("end_seconds must not be earlier than start_seconds")
        return self


class DiagramRecommendation(StrictModel):
    diagram_type: RenderedDiagramType
    label: ShortText
    rationale: DescriptionText
    score: float = Field(ge=0, le=1)


class VisualOutlineSection(StrictModel):
    id: Identifier
    title: ShortText
    core_message: DescriptionText
    key_points: list[DescriptionText] = Field(min_length=2, max_length=5)
    evidence_queries: list[ShortText] = Field(min_length=2, max_length=8)
    recommended_block_type: Literal[
        "concept_chain",
        "process_flow",
        "comparison",
        "paired_contrast",
        "signal_flow",
        "decision_axis",
        "hierarchy",
        "timeline",
        "concept_grid",
        "mind_map",
        "callout",
    ]


class VisualOutline(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    thesis: DescriptionText
    audience_goal: Annotated[str, Field(min_length=1, max_length=160)]
    sections: list[VisualOutlineSection] = Field(min_length=4, max_length=8)

    @model_validator(mode="after")
    def validate_section_ids(self) -> "VisualOutline":
        section_ids = [section.id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("outline section ids must be unique")
        return self


class BlockBase(StrictModel):
    id: Identifier
    title: ShortText
    source_ref_ids: list[Identifier] = Field(min_length=1, max_length=16)


class HeroSummaryBlock(BlockBase):
    type: Literal["hero_summary"]
    headline: ShortText
    summary: DescriptionText
    points: list[ShortText] = Field(min_length=1, max_length=5)


class LabeledItem(StrictModel):
    id: Identifier
    label: ShortText
    description: DescriptionText
    why_needed: Optional[DescriptionText] = None
    mechanism: Optional[DescriptionText] = None
    example: Optional[DescriptionText] = None
    misconception: Optional[DescriptionText] = None


class ConceptChainBlock(BlockBase):
    type: Literal["concept_chain"]
    items: list[LabeledItem] = Field(min_length=2, max_length=10)


class ProcessFlowBlock(BlockBase):
    type: Literal["process_flow"]
    steps: list[LabeledItem] = Field(min_length=2, max_length=10)


class ComparisonItem(StrictModel):
    label: ShortText
    description: DescriptionText


class ComparisonColumn(StrictModel):
    title: ShortText
    items: list[ComparisonItem] = Field(min_length=1, max_length=8)


class ComparisonBlock(BlockBase):
    type: Literal["comparison"]
    columns: list[ComparisonColumn] = Field(min_length=2, max_length=4)


class ContrastPair(StrictModel):
    bad_label: ShortText
    bad_signal: SignalText
    risk_label: ShortText
    better_label: ShortText
    better_signal: Optional[SignalText] = None


class PairedContrastBlock(BlockBase):
    type: Literal["paired_contrast"]
    pairs: list[ContrastPair] = Field(min_length=2, max_length=6)


class SignalFlowStep(StrictModel):
    label: ShortText
    description: SignalText


class SignalFlowBlock(BlockBase):
    type: Literal["signal_flow"]
    steps: list[SignalFlowStep] = Field(min_length=2, max_length=6)
    outcome_label: Optional[ShortText] = None


class DecisionAxisLabels(StrictModel):
    low: ShortText
    high: ShortText


class DecisionAxisQuadrant(StrictModel):
    label: ShortText
    description: Optional[SignalText] = None
    x: Literal["low", "high"]
    y: Literal["low", "high"]
    tone: Literal["good", "neutral", "warning", "bad"] = "neutral"


class DecisionAxisBlock(BlockBase):
    type: Literal["decision_axis"]
    x_axis: DecisionAxisLabels
    y_axis: DecisionAxisLabels
    quadrants: list[DecisionAxisQuadrant] = Field(min_length=2, max_length=4)


class HierarchyNode(LabeledItem):
    parent_id: Optional[Identifier] = None


class HierarchyBlock(BlockBase):
    type: Literal["hierarchy"]
    nodes: list[HierarchyNode] = Field(min_length=2, max_length=16)

    @model_validator(mode="after")
    def validate_tree(self) -> "HierarchyBlock":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("hierarchy node ids must be unique")

        known_ids = set(node_ids)
        parents = {node.id: node.parent_id for node in self.nodes}
        for node_id in node_ids:
            visited: set[str] = set()
            current: Optional[str] = node_id
            while current is not None:
                if current in visited:
                    raise ValueError("hierarchy must not contain cycles")
                visited.add(current)
                parent = parents.get(current)
                if parent is not None and parent not in known_ids:
                    raise ValueError("hierarchy parent_id must reference a node")
                current = parent
        return self


class TimelineEvent(StrictModel):
    label: ShortText
    description: DescriptionText
    time_label: ShortText


class TimelineBlock(BlockBase):
    type: Literal["timeline"]
    events: list[TimelineEvent] = Field(min_length=2, max_length=12)


class ConceptGridItem(StrictModel):
    label: ShortText
    description: DescriptionText
    why_needed: Optional[DescriptionText] = None
    mechanism: Optional[DescriptionText] = None
    example: Optional[DescriptionText] = None
    misconception: Optional[DescriptionText] = None


class ConceptGridBlock(BlockBase):
    type: Literal["concept_grid"]
    items: list[ConceptGridItem] = Field(min_length=2, max_length=12)


class MindMapBranch(StrictModel):
    label: ShortText
    children: list[ShortText] = Field(min_length=1, max_length=6)


class MindMapBlock(BlockBase):
    type: Literal["mind_map"]
    center_label: ShortText
    branches: list[MindMapBranch] = Field(min_length=2, max_length=8)


class CalloutBlock(BlockBase):
    type: Literal["callout"]
    tone: Literal["key", "warning", "tip", "mistake"]
    text: DescriptionText


class ReviewQuestion(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=160)]
    answer: DescriptionText


class ReviewQuestionsBlock(BlockBase):
    type: Literal["review_questions"]
    questions: list[ReviewQuestion] = Field(min_length=2, max_length=8)


VisualBlock = Annotated[
    Union[
        HeroSummaryBlock,
        ConceptChainBlock,
        ProcessFlowBlock,
        ComparisonBlock,
        PairedContrastBlock,
        SignalFlowBlock,
        DecisionAxisBlock,
        HierarchyBlock,
        TimelineBlock,
        ConceptGridBlock,
        MindMapBlock,
        CalloutBlock,
        ReviewQuestionsBlock,
    ],
    Field(discriminator="type"),
]


class VisualPage(StrictModel):
    id: Identifier
    title: ShortText
    learning_goal: Annotated[str, Field(min_length=1, max_length=160)]
    transition: Optional[DescriptionText] = None
    blocks: list[VisualBlock] = Field(min_length=1, max_length=12)


class VisualDocument(StrictModel):
    version: Literal[1] = 1
    document_type: DocumentType
    title: Annotated[str, Field(min_length=1, max_length=160)]
    subtitle: Optional[Annotated[str, Field(min_length=1, max_length=240)]] = None
    recommended_style: ThemeId = "study-notes"
    selected_diagram_type: Optional[RenderedDiagramType] = None
    diagram_recommendations: list[DiagramRecommendation] = Field(
        default_factory=list,
        max_length=3,
    )
    pages: list[VisualPage] = Field(min_length=1, max_length=9)
    source_refs: list[SourceReference] = Field(min_length=1)

    @field_validator("diagram_recommendations", mode="before")
    @classmethod
    def sort_recommendations(cls, value):
        if not isinstance(value, list):
            return value
        return sorted(
            value,
            key=lambda item: item.get("score", 0) if isinstance(item, dict) else item.score,
            reverse=True,
        )[:3]

    @model_validator(mode="after")
    def validate_document_shape(self) -> "VisualDocument":
        if self.selected_diagram_type is None and self.diagram_recommendations:
            self.selected_diagram_type = self.diagram_recommendations[0].diagram_type
        if self.document_type == "full_note":
            if len(self.pages) < 3:
                raise ValueError("full_note must contain at least three pages")
            has_review = any(
                isinstance(block, ReviewQuestionsBlock)
                for block in self.pages[-1].blocks
            )
            if not has_review:
                raise ValueError(
                    "the final full_note page must contain review_questions"
                )
        return self
