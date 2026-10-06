# IFC2RDF

IFC2RDF is a case-study converter for connecting IFC building-service assets to
Brick RDF. Its primary semantic input is a **BDNS classification registered in
the IFC model**, not an equipment `Name` that merely resembles a BDNS label.

The implementation demonstrates three things:

1. mapping BDNS-classified IFC equipment to Brick classes;
2. connecting BMS point metadata to that equipment; and
3. deriving Brick relationships from IFC relationships, with provenance.

It is a research prototype and does not claim to be a general IFC-to-Brick
converter or an authoritative BDNS-to-Brick standard mapping.

No project IFC model, project BMS export, converted RDF, GUID, coordinate, or
project-specific validation result is included in this repository. The public
example is generated synthetically at runtime.

## Processing flow and modules

The processing steps remain separated so that each stage can be inspected and
tested independently:

| Stage | Module | Responsibility |
| --- | --- | --- |
| 1 | `src/ifc.py` | Load IFC; extract BDNS classifications, spatial elements, containment, ports, and connections |
| 2 | `src/mapping.py` | Apply the project BDNS-to-Brick crosswalk and retain unresolved equipment |
| 3 | `src/points.py` | Load BMS point metadata and link points using explicit BDNS identifiers |
| 4 | `src/rdf.py` | Build Brick/BOT RDF and write relationship provenance |
| 5 | `src/validation.py` | Report unresolved mappings, relationships, and BMS point links |
| 6 | `src/app/pipeline.py` | Execute the stages in order without embedding project data |
| 7 | `src/run.py` | Provide the command-line interface |

## IFC input contract

BDNS assignments are read in this order:

```text
IfcClassification(Name = "BDNS")
  -> IfcClassificationReference(Identification / ItemReference / Name)
  -> IfcRelAssociatesClassification
  -> IfcDistributionElement
```

The classification reference value is the BDNS code used by the project
crosswalk. `GlobalId` remains the stable RDF identity. `Name` is retained only
as a human-readable label; it is not treated as proof of a BDNS assignment.

This distinction is intentional. BDNS defines identifiers such as `asset.guid`
and `asset.name`, but it does not by itself require every IFC authoring tool to
store `asset.name` in the IFC `Name` attribute. This case study therefore uses
the explicit IFC classification relationship as its primary, auditable source.

Assets without an explicit BDNS classification are not silently discarded.
They are emitted as `brick:Equipment`, marked
`missing_bdns_classification`, and listed for review.

## Relationship policy

The converter prioritizes explicit IFC relationships:

| IFC evidence | Brick output | Provenance method |
| --- | --- | --- |
| `IfcRelAggregates` | spatial `brick:hasPart` | explicit |
| `IfcRelContainedInSpatialStructure` | `brick:hasLocation` | explicit |
| `IfcRelConnectsPortToElement` / IFC4 port nesting + `IfcRelConnectsPorts` + `FlowDirection` | `brick:feeds` | derived |
| BMS point CSV matched by BDNS classification value | `brick:hasPoint` | explicit BDNS identifier |

Ambiguous port connections are reported and are not converted into directional
`brick:feeds` assertions. Optional geometry fallback is available only for
equipment lacking explicit containment. It uses an AABB centroid test, never
overrides explicit relationships, and marks every inferred result as
review-required with lower confidence.

## Outputs

Each run produces:

- `building_brick.ttl` — Brick/BOT RDF in Turtle;
- `requirement_report.json` — capability-level IFC input audit;
- `provenance.csv` — evidence, method, confidence, and review status for mappings and relationships;
- `validation_report.json` — unresolved mappings, inferred relationships, and BMS links.

The capability audit separates `IDENTITY`, `CLASSIFICATION`,
`SPATIAL_HIERARCHY`, `LOCATION`, and `FLOW_TOPOLOGY`. A missing optional
capability does not prevent the converter from producing the RDF that the IFC
evidence supports.

## Installation

Python 3.10 or later is recommended.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

On Windows, use `.venv\Scripts\pip` for the second command.

## Usage

From the repository root:

```bash
python src/run.py \
  --ifc path/to/model.ifc \
  --out data/output \
  --base-ns https://example.org/my-building#
```

To add BMS points:

```bash
python src/run.py \
  --ifc path/to/model.ifc \
  --points-csv path/to/points.csv \
  --out data/output
```

The point CSV columns are `point_id`, `name`, `unit`, and
`bdns_abbreviation`. The latter should equal the classification reference value
used for the target IFC equipment. Legacy matching against IFC `Name` is kept
as a compatibility fallback and is marked review-required.

Geometry fallback must be requested explicitly:

```bash
python src/run.py --ifc path/to/model.ifc --out data/output --geometry-fallback
```

## Fully synthetic example

The example creates a temporary IFC4 model containing:

- an explicit `IfcClassification(Name="BDNS")`;
- `AHU-1` and `FCU-1` classification references;
- two classified equipment objects in one synthetic space;
- SOURCE/SINK distribution ports and one explicit port connection; and
- two synthetic BMS points linked by the classification reference values.

Run it from the repository root:

```bash
python examples/run_synthetic_example.py
```

Inputs and outputs are written below `examples/generated/`, which is excluded
from Git. The run is expected to produce two equipment entities, two
`brick:hasLocation` relationships, one `brick:feeds` relationship, two
`brick:hasPoint` relationships, and no review-required records.

## Mapping policy

`data/resources/BDNS mapping partial.csv` is a project-defined research
crosswalk. A unique row produces a project-defined Brick class. Missing or
ambiguous mappings fall back to `brick:Equipment` and require review. The
repository does not present this crosswalk as an official mapping issued by
BDNS, Brick, or buildingSMART.

## Current limitations

- IFC2x3 is the tested schema. IFC4 port ownership via `IfcRelNests` is
  implemented but not yet validated with the case-study dataset.
- The project crosswalk is partial and experimental.
- Geometry fallback is approximate and must be reviewed.
- Full Brick SHACL validation is future work; the current validation report is
  a project-level completeness check.
- Real-time BMS transport is out of scope. BMS integration is demonstrated via
  point metadata and `brick:hasPoint` links.
