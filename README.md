# IFC2RDF

IFC2RDF is a case-study converter for connecting equipment from one or more MEP
IFC models with spaces from one or more architectural IFC models and publishing
the result as Brick RDF. Its primary semantic input is a **BDNS classification
registered in a MEP IFC model**, not an equipment `Name` that merely resembles
a BDNS label.

The implementation demonstrates three things:

1. mapping BDNS-classified IFC assets to Brick or BOT classes;
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
| 1 | `src/ifc.py` | Load multiple MEP/ARC IFC files; extract BDNS equipment, ARC spaces, containment, ports, and connections |
| 2 | `src/mapping.py` | Apply the project BDNS-to-Brick/BOT crosswalk and retain unresolved assets |
| 3 | `src/points.py` | Load BMS point metadata and link points using explicit BDNS identifiers |
| 4 | `src/rdf.py` | Build Brick/BOT RDF and write relationship provenance |
| 5 | `src/validation.py` | Report unresolved mappings, relationships, and BMS point links |
| 6 | `src/app/pipeline.py` | Execute the stages in order without embedding project data |
| 7 | `src/run.py` | Provide the command-line interface |

## IFC input contract

The two IFC roles are intentionally separate:

- MEP IFC files provide BDNS-classified equipment, distribution ports,
  equipment connectivity, and any explicit containment references.
- ARC IFC files provide the authoritative Site/Building/Storey/Space hierarchy
  and spatial attributes.

Both roles accept multiple files. ARC spatial attributes replace MEP spatial
stubs when their `GlobalId` values match.

BDNS assignments are read in this order:

```text
IfcClassification(Name = "BDNS")
  -> IfcClassificationReference(Identification / ItemReference / Name)
  -> IfcRelAssociatesClassification
  -> IfcDistributionElement
```

In this representation, `IfcClassification.Name` identifies the classification
system as BDNS. The BDNS tag is stored by the associated
`IfcClassificationReference` (`ItemReference` in IFC2x3 or `Identification` in
newer IFC schemas, with `Name` accepted only as a reference-field fallback).
`IfcRelAssociatesClassification.RelatedObjects` links that reference to the IFC
equipment entity. The equipment entity's ordinary `Name` attribute is not the
BDNS tag store and is never used to infer that an object is BDNS-classified.

The classification reference value is the BDNS code used by the project
crosswalk. `GlobalId` remains the stable RDF identity. `Name` is retained only
as a human-readable label; it is not treated as proof of a BDNS assignment.

Only IFC equipment with an explicit BDNS classification association enters the
mapping, relationship reasoning, and RDF stages. Other IFC distribution
elements remain visible in the input audit but are not passed to the mapping
CSV and are not RDF conversion candidates. The mapping CSV is used only as a
BDNS-tag-to-Brick/BOT-class lookup; it does not classify equipment from IFC
entity type or `Name`.

This distinction is intentional. BDNS defines identifiers such as `asset.guid`
and `asset.name`, but it does not by itself require every IFC authoring tool to
store `asset.name` in the IFC `Name` attribute. This case study therefore uses
the explicit IFC classification relationship as its primary, auditable source.

BDNS-classified assets without a verified ontology class are marked `tbd` for
review. They and their dependent relationships are omitted from RDF rather
than being forced into a generic class. Assets without BDNS are outside the
mapping and RDF candidate set.

## Relationship policy

The converter prioritizes explicit IFC relationships:

| IFC evidence | Brick output | Provenance method |
| --- | --- | --- |
| `IfcRelAggregates` | spatial `brick:hasPart` | explicit |
| `IfcRelContainedInSpatialStructure` | `brick:hasLocation` | explicit |
| `IfcRelConnectsPortToElement` / IFC4 port nesting + `IfcRelConnectsPorts` + `FlowDirection` | `brick:feeds` | derived |
| BMS point CSV matched by BDNS classification value | `brick:hasPoint` | explicit BDNS identifier |

`SOURCE`/`SINK` is used directly. A `SOURCEANDSINK` port is assigned a direction
only when its connected peer is explicitly `SOURCE` or `SINK`; connections that
remain ambiguous are recorded but are not converted into directional
`brick:feeds` assertions. Every port-level decision is written to
`connection_inference.csv` with its IFC relationship, endpoint ports and
equipment, method, confidence, and review status. Optional geometry fallback is available only for
equipment lacking explicit containment. It compares each MEP equipment
centroid against ARC `IfcSpace` AABBs, never overrides explicit relationships,
and marks every inferred result as review-required with lower confidence.

BMS points receive spatial context through the two-hop Brick path
`Point <- brick:hasPoint - Equipment -> brick:hasLocation -> Space`. The
converter does not assert `brick:hasLocation` directly on a Point. Geometry
coordinates are normalized to metres before cross-model comparison. If MEP and
ARC models declare conflicting projected coordinate reference systems,
geometry inference is stopped and the conflict is reported.

## Outputs

Each run produces:

- `building_brick.ttl` — Brick/BOT RDF in Turtle;
- `equipment_mapping.csv` — one IFC asset per row with its BDNS code, target ontology class, status, and provenance;
- `connection_inference.csv` — one BDNS-equipment port connection per row, including directed and unresolved decisions;
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
  --mep-ifc path/to/mep-a.ifc path/to/mep-b.ifc \
  --arc-ifc path/to/arc-a.ifc path/to/arc-b.ifc \
  --out data/output \
  --base-ns https://example.org/my-building#
```

To add BMS points:

```bash
python src/run.py \
  --mep-ifc path/to/mep.ifc \
  --arc-ifc path/to/arc.ifc \
  --points-csv path/to/points.csv \
  --out data/output
```

The point CSV columns are `point_id`, `name`, `unit`, and
`bdns_abbreviation`. The latter should equal the classification reference value
used for the target IFC equipment. Legacy matching against IFC `Name` is kept
as a compatibility fallback and is marked review-required.

Geometry fallback must be requested explicitly:

```bash
python src/run.py \
  --mep-ifc path/to/mep.ifc \
  --arc-ifc path/to/arc.ifc \
  --out data/output \
  --geometry-fallback
```

## Fully synthetic example

The example creates two temporary MEP IFC4 models and two temporary ARC IFC4
models containing:

- an explicit `IfcClassification(Name="BDNS")`;
- `AHU-1` and `FCU-1` classification references;
- three classified equipment objects in two ARC spaces;
- SOURCE/SINK distribution ports and one explicit port connection; and
- three synthetic BMS points linked by the classification reference values.

Run it from the repository root:

```bash
python examples/run_synthetic_example.py
```

Inputs and outputs are written below `examples/generated/`, which is excluded
from Git. The run is expected to produce three equipment entities, three
`brick:hasLocation` relationships, one `brick:feeds` relationship, three
`brick:hasPoint` relationships, and no review-required records.

## Mapping policy

`data/resources/BDNS mapping partial.csv` is a project-defined research
crosswalk. A unique verified row produces a project-defined Brick or BOT class.
Class selection is based on the semantic text in `bdns_tag`; `raw_ifc_class` is
retained for audit and does not decide the mapping. Spatial tags use BOT:
`architecture - room` and `space` map to `bot:Space`, while `spatial zone` and
`zone` map conservatively to their containing parent class `bot:Zone`. A word
such as “room” inside an equipment tag does not make that asset spatial.
The BDNS `SG` tag (`air terminal - grille - supply`) maps to
`brick:Air_Diffuser`. Brick 1.4.4 defines `Air_Diffuser` as a subclass of
`Terminal_Unit` but has no separate `Supply_Air_Diffuser` class, so supply
direction remains BDNS provenance rather than a more specific Brick type.

Rows reviewed against Brick 1.4.4 carry a `mapping_method` of
`brick144_exact`, `brick144_close`, `brick144_broader`, or
`brick144_no_match`, and a `mapping_rationale`. `close` means the Brick
definition fits although the names differ; `broader` uses the nearest correct
ancestor class but never the root `brick:Equipment`; `no_match` stays `tbd`.
Physical devices are mapped to Equipment classes only: Brick `*_Sensor` and
`Alarm` classes are Points, so sensor tags use `Sensor_Equipment` subclasses,
and system tags (`brick:System` is a Collection) stay `tbd`. Ductwork, pipework,
cable trays, and cable ladders have no Brick 1.4.4 Equipment class and stay
`tbd`. `data/resources/brick_1.4.4_equipment_classes.json` lists the
non-deprecated Brick 1.4.4 Equipment classes, and the test suite rejects any
mapped `brick:` class outside it. Every equipment row has been reviewed this
way; the BOT spatial rows keep their `bdns_tag_bot_*` methods. Systems,
structure, furniture, appliances, sanitary terminals, and virtual devices have
no Brick 1.4.4 Equipment class and stay `tbd`.
Missing, ambiguous, or unsupported mappings use `tbd`; those assets are listed
for review and omitted from RDF. The repository does not present this
crosswalk as an official mapping issued by BDNS, Brick, BOT, or buildingSMART.

This CSV is an interim case-study artifact, not a standards deliverable. When a
versioned BDNS-to-Brick/BOT mapping is published and maintained through the
[buildingSMART Data Dictionary (bSDD)](https://www.buildingsmart.org/users/services/buildingsmart-data-dictionary/)
by the responsible standards organisation, the converter should use that
mapping in preference to this CSV. Adoption must verify the bSDD dictionary
owner, version, status, and class URIs; publication in bSDD alone does not make
third-party content an official BDNS or Brick mapping. The bSDD API is the
intended machine-readable access path; see the
[official API guidance](https://technical.buildingsmart.org/services/bsdd/using-the-bsdd-api/).

## Current limitations

- The public automated example tests IFC4. IFC2x3 port ownership via
  `IfcRelConnectsPortToElement` is implemented but needs a public synthetic
  regression fixture.
- The project crosswalk is partial and experimental.
- Geometry fallback is approximate and must be reviewed.
- Full Brick SHACL validation is future work; the current validation report is
  a project-level completeness check.
- Real-time BMS transport is out of scope. BMS integration is demonstrated via
  point metadata and `brick:hasPoint` links.
