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

Only IFC equipment with an explicit BDNS classification association whose
value is an asset instance ID enters the mapping, relationship reasoning, and
RDF stages. An instance ID is the BDNS abbreviation, a hyphen, and a number
(for example `AHU-00001`); the abbreviation is looked up in the crosswalk.
Elements whose BDNS tag holds only an abbreviation (for example `AHU` shared by
every AHU) are left out and listed in `bdns_tag_issues.csv`, together with any
instance ID used by more than one element. Other IFC distribution
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
| MEP equipment geometry inside an ARC `IfcSpace` plan footprint on the same storey | `brick:hasLocation` | `geometric_plan_containment_same_storey` |
| `IfcRelConnectsPortToElement` / IFC4 port nesting + `IfcRelConnectsPorts` + `FlowDirection` | `brick:feeds` | derived |
| BMS point list `equipment_ref` / `space_ref` (stage 3) | `brick:hasPoint` | BDNS instance ID / IFC space Name |

`brick:feeds` is inferred from paths through the whole MEP port graph, not
only from directly connected equipment:

- Only connections whose ports are explicitly `SOURCE` -> `SINK` give a
  direction. `SOURCEANDSINK` connections are never forced into a direction, so
  a path that needs one is not inferred.
- Elements that are not mapped equipment (ductwork, pipework, fittings, `tbd`
  tags, unclassified elements) are traversed as path evidence and never become
  RDF entities.
- BDNS tags listed as `passthrough` in `data/resources/topology_roles.csv`
  (duct dampers and silencers) are traversed too. That equipment keeps its own
  class and location in RDF but is not a `brick:feeds` node, so
  `AHU -> fire damper -> VAV` becomes `AHU feeds VAV`, and the damper is listed
  in the path's `traversed_equipment_guids`. A path stops at the first node
  equipment it reaches.
- Parallel connections on the same element pair may assert opposite
  directions; both readings are kept as candidates.
- Role check: Brick 1.4.4 defines `Air_Diffuser` as delivering air into a
  room, so a path starting at an air diffuser is a `role_conflict` and is not
  written to RDF. If both A -> B and B -> A survive, both are a
  `direction_conflict` and neither is written.
- A feed whose path crosses an element pair with opposing directions is kept
  only when the opposite reading fails the role check; it is written with
  confidence 0.8 and marked review-required.
- IFC system membership is not used yet.

Every path, including conflicts, is written to `topology_paths.csv` with the
traversed element GUIDs and connection IDs, so each `brick:feeds` can be traced
back to IFC evidence. `connection_inference.csv` still records the direct
port-level decision for every connection between two BDNS-classified elements.

MEP models often contain equipment only in storeys. `src/spaces.py` places
equipment in ARC spaces with one deterministic rule (on by default; disable
with `--skip-space-inference`):

1. Coordinate frames must agree: every storey present in both models (same
   GlobalId) must have the same placement origin, otherwise nothing is
   inferred.
2. The reference point is the centre of the equipment's own geometry, in
   metres.
3. Its height must lie between the floor level of the storey the equipment is
   explicitly contained in and the next storey's floor level; otherwise the
   explicit storey contradicts the geometry (`storey_mismatch`) and nothing is
   inferred.
4. Candidates are only the spaces aggregated under that same storey.
5. The point must lie inside the space's plan footprint: the space geometry's
   triangles projected onto the plan, not its bounding box.
6. Exactly one space -> `equipment brick:hasLocation space`. None or several
   -> no relation.

Height inside the space is not required, because ceiling-mounted and
ceiling-void equipment sits above the space volume; it is recorded as
evidence. Every decision and its reason is written to `space_locations.csv`,
and equipment explicitly contained in a space keeps that relation.

BMS points receive spatial context either through the two-hop Brick path
`Point <- brick:hasPoint - Equipment -> brick:hasLocation -> Space`, or directly
as `Space brick:hasPoint Point` when the point list names a space. The
converter does not assert `brick:hasLocation` directly on a Point.

## Outputs

Each run produces:

- `building_brick.ttl` — Brick/BOT RDF in Turtle;
- `equipment_mapping.csv` — one IFC asset per row with its BDNS code, target ontology class, status, and provenance;
- `connection_inference.csv` — one BDNS-equipment port connection per row, including directed and unresolved decisions;
- `topology_paths.csv` — one equipment-to-equipment flow path per row with status (`inferred`, `role_conflict`, `direction_conflict`), traversed pass-through equipment, elements and connections, confidence, and review status;
- `space_locations.csv` — one equipment per row with its space decision (`located`, `outside`, `ambiguous`, `storey_mismatch`, `no_geometry`, `no_storey`, `explicit_space`), reference point, height relation, and reason;
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

BMS points are added by stages 2 and 3 below.

### Staged workflow (IFC, BMS points, match, GraphDB)

The user provides three inputs: the MEP IFC with BDNS-classified equipment,
an IFC with the spatial structure (for example the architectural model), and
the BMS point list. The BDNS-to-Brick crosswalk is bundled in
`data/resources/`. Everything runs locally.

The easiest way is the local web UI, which runs each stage on a button and
shows its summary, output files, and graph view:

```bash
python src/ui.py
```

It listens on `http://127.0.0.1:8765` only and takes local file paths; nothing
is uploaded. Each input has a **Browse…** button that opens the Windows file
or folder dialog on the same PC and fills in the full path. The GraphDB home
is the GraphDB distribution folder (for example `graphdb-11.3.0`, the folder
that contains `bin/`); it is only needed when the UI has to start GraphDB.

Its GraphDB panel works on the loaded repository without the GraphDB
Workbench: it shows whether GraphDB is running and can start it from the
GraphDB home folder, searches equipment, spaces, and points by IFC Name or
point ID, draws a node's neighbors (double-click a node to expand it) or its
whole `brick:feeds` path upstream and downstream, and lists all feeds,
unlinked points, and unclassified points. The queries live in
`src/explorer.py`. The page loads `vis-network` from unpkg, so the graph needs
an internet connection.

Run each stage alone, or all of them with `src/run_all.py`. Each stage writes
to its own folder so it can be reviewed before the next one:

| Stage | Script | Output |
| --- | --- | --- |
| 1 IFC -> RDF | `src/run.py` | `building_brick.ttl`, mapping, topology and validation files |
| 2 point list -> RDF | `src/run_points.py` | `points_brick.ttl`, `point_classification.csv`, `point_list_issues.csv`, `points_report.json` |
| 3 match and validate | `src/run_match.py` | `linked_brick.ttl`, `match_results.csv`, `match_report.json` |
| 4 GraphDB and view | `src/run_graphdb.py` | GraphDB repository, `graph_view.html`, `graphdb_report.json` |

From the repository root:

```bash
python src/run_all.py \
  --mep-ifc path/to/mep.ifc --arc-ifc path/to/arc.ifc \
  --points-csv path/to/point_list.csv \
  --out data/output/stages \
  --graphdb-home path/to/graphdb-11.3.0
```

The terminal and the UI run the same code with the same options:
`--skip-space-inference` turns off the geometry-based equipment-to-space
step, `--local-view` writes `graph_view.html` without GraphDB, and
`--skip-graphdb` stops after stage 3. Each stage script accepts `--help`. In
PowerShell, continue lines with a backtick instead of a backslash.

The point list is a BACnet-style CSV with the columns `point_id`,
`object_name`, `description`, `object_type` (AI, AO, AV, BI, BO, BV, MI, MO,
MV), `device_instance`, `object_instance`, `units`, `equipment_ref`, and
`space_ref`. It is a simplified BACnet point schedule, not a full EDE file. A
BMS point list carries no Brick class; stage 2 assigns one.

- `equipment_ref` is the BDNS asset instance ID (for example `AHU-00001`). It
  is matched only to the equipment whose BDNS classification value is that
  ID; the IFC `Name` is not used. `match_results.csv` records how each point
  was linked or why it was not.
- `match_report.json` reports two results: `conforms` is true when no link is
  ambiguous or review-required, and `complete` is true when every point is
  linked. Unresolved references (for example a room missing from the IFC) make
  the result incomplete without making the links themselves invalid.
- `space_ref` is matched to the IFC `Name` of an ARC `IfcSpace` (for example
  `01-02`). Real BMS exports often hold free-text room names, which would need
  a name-to-room-number table first.
- Exactly one of `equipment_ref` and `space_ref` is required. Matches become
  `<equipment or space> brick:hasPoint <point>`.

Stage 2 converts Sensor and Setpoint points only. Each point's Brick class is
assigned by `src/point_classes.py` without project-specific rules, by matching
words against the Brick class names in `data/resources/brick_classes.json`
(for example `Supply_Air_Temperature_Sensor` = Supply + Air + Temperature +
Sensor). That list holds every non-deprecated Brick 1.4.4 Sensor and Setpoint
class. It is generated from the official release file with
`python tools/build_point_class_list.py Brick.ttl data/resources/brick_classes.json`
(Brick.ttl from https://github.com/BrickSchema/Brick/releases/download/v1.4.4/Brick.ttl).
Deprecated classes such as `Supply_Water_Temperature_Sensor` are never
assigned; such a point gets the broader class its name supports
(`Water_Temperature_Sensor`), because the official replacement (`Leaving_*` or
`Entering_*`) depends on the equipment and is not stated in the name.

- Words come from the point name and description, normalised with a general
  HVAC vocabulary (`temp` -> Temperature, `rh` -> Humidity, `room` -> Zone,
  `SAT` -> Supply Air Temperature, ...).
- The BACnet object type gives the kind: AI is a Sensor; AV is a Setpoint
  only when a setpoint word is present; BI is a Sensor only for binary-sensor
  words such as occupancy or motion. Outputs (AO, BO, MO), status and other
  value objects are out of scope: they are listed in
  `point_classification.csv` and left out of the RDF. The ambiguous `sp` is
  static pressure on an input and a setpoint on a value object.
- The unit gives or checks the measured quantity (`degC` -> Temperature,
  `ppm` -> a gas named in the point); a unit that contradicts the name stops
  the assignment.
- The equipment's BDNS abbreviation, looked up in the bundled crosswalk, gives
  the medium (Air for air handling units, VAV boxes, fan coil units, ...;
  Water for pumps, chillers, ...); a space point adds Zone and Air.
- The chosen class is the most specific class whose words are all among the
  point's words. Words the point does not have are never added, so a VAV
  "Zone Air Flow" point becomes `Air_Flow_Sensor`, not
  `Supply_Air_Flow_Sensor`. No match or a tie leaves the point a plain
  `brick:Point` marked `unclassified` for review.

The procedure is deterministic, runs locally, and uses no language model or
external service. Unknown spellings are not guessed; add them to the
vocabulary in `src/point_classes.py`.

Stage 4 starts GraphDB from `--graphdb-home` if it is not running, creates the
`--repository` (default `IFC2RDF_case_study`) if missing, replaces its
statements with `linked_brick.ttl`, and writes `graph_view.html`: equipment on
`brick:feeds` paths with their points and locations, and spaces with their
points. The page loads `vis-network` from unpkg. `--local-view` builds the
same page from the RDF file with rdflib, without GraphDB. Other GraphDB
repositories are not touched. GraphDB refuses writes when its disk is nearly
full.

`tools/convert_legacy_point_list.py` converts the legacy research point list
(`point_id`, `name`, `unit`, `bdns_abbreviation`, `space_id`) to this format;
its BACnet object types and readable names come from the legacy name pattern,
and its device and object instances are synthetic numbering.

## Fully synthetic example

The example creates two temporary MEP IFC4 models and two temporary ARC IFC4
models containing:

- an explicit `IfcClassification(Name="BDNS")`;
- `AHU-1` and `FCU-1` classification references;
- three classified equipment objects in two ARC spaces;
- SOURCE/SINK distribution ports and one explicit port connection; and
- three synthetic BMS points (stage 2 format) linked in stage 3 by the
  classification reference values.

Run it from the repository root:

```bash
python examples/run_synthetic_example.py
```

Inputs and outputs are written below `examples/generated/`, which is excluded
from Git, in `1_ifc/`, `2_points/`, and `3_match/`. The run is expected to
produce three equipment entities, three `brick:hasLocation` relationships, one
`brick:feeds` relationship, three `brick:hasPoint` relationships, and no
review-required records.

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
- The project crosswalk is partial and experimental. Ductwork, pipework,
  cable trays, systems, and other tags without a Brick 1.4.4 Equipment class
  stay `tbd` and are left out of the RDF.
- Only elements whose BDNS tag is an asset instance ID (for example
  `AHU-00001`) are converted. A model that carries only type-level tags (for
  example `AHU`) has to be given instance IDs before it is used; that step is
  not part of this tool.
- `brick:feeds` is derived only from explicit port connections with SOURCE and
  SINK flow directions. A model without port connections yields few or no
  feeds.
- Space inference needs equipment geometry, ARC space geometry, and shared
  storey GlobalIds; equipment whose explicit storey contradicts its geometry is
  not placed. It takes minutes on large models (about 8 minutes for some
  6,500 equipment elements).
- Stage 2 converts Sensor and Setpoint points only. Classes come from English
  point words, the BACnet object type, and the unit; when words are missing a
  broader class is used rather than a guessed one. The point list is a
  simplified BACnet schedule, not a full EDE file.
- `space_ref` must equal the `Name` of an ARC `IfcSpace`; free-text room names
  need a name-to-room table first.
- Full Brick SHACL validation is future work; the current validation report is
  a project-level completeness check.
- The graph view loads `vis-network` from unpkg and needs an internet
  connection; large graphs are crowded.
- Stage 4 was tested with GraphDB 11.3. It replaces all statements in the
  chosen repository, and GraphDB refuses writes when its disk is nearly full.
- The UI is for one user on the same PC (127.0.0.1). Its Browse buttons use
  the Windows file dialog through Python's tkinter.
- Real-time BMS transport is out of scope. BMS integration is demonstrated via
  point metadata and `brick:hasPoint` links.
