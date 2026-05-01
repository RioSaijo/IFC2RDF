# Converter from IFC to RDF(This project is under development.)
## Transforming IFC for Smart Building Platforms

## Project overview
This repository presents a Converter from IFC to RDF developed and applied as a case study within the SMART Building Data to OpenBIM Interoperability Project.

## Purpose
This project aims to fundamentally enhance interoperability between smart building operations and IFC-based building information models by developing and releasing an IFC to RDF conversion program. We position this as a preliminary prototype that contributes to standard‑development efforts in semantic integration for the foundational frameworks of future smart buildings.

## Scope of the case study
The scope of this case study is as follows.

- Provision of a converter program to transform IFC based architectural models into RDF representations.

- Experimental alignment of IFC based concepts and Brick Schema concepts via **BDNS tags**.  
  In this context , BDNS functions as a semantic tagging layer that supports interoperability between IFC and Brick.  
  This repository provides alignment definitions between BDNS tags and the Brick Schema.

## Input and output

### Input

The current implementation takes IFC STEP files with instance data as input, specifically `.ifc` files.

At present, the converter has been applied and tested with IFC 2x3 models.  
Although only IFC 2x3 is explicitly tested at this stage, the overall approach is intended to be extensible to IFC4 and later versions in future development.

```text
ここでifcデータにおけるBDNSタグの格納形式・BDNSタグのSyntaxについて述べます．
```

IFCデータにおけるBDNSタグの格納形式と、そのSyntax（構文）上の制限に関するREADME用の英文セクション案を作成しました。

以前の対話で確認した「DSSO-00001」のような形式がなぜ不適切（不健全）とされるのかという背景を含め、文献に基づいた正確な仕様を反映させています。

***

### BDNS Tag Syntax and Storage in IFC

#### 1. Identification Strategy in IFC Models
In accordance with the BDNS specification, each device or asset within an `.ifc` file must be assigned two distinct identifiers:

*   **Device/Asset Instance GUID (`asset.guid`)**: A machine-readable, 128-bit auto-generated number. For IFC workflows, this is represented by the 22-character IFC base-64 encoding (the `GlobalId` attribute).
*   **Device/Asset Role Name (`asset.name`)**: A human-generated, human-readable identifier that remains fixed for a specific function even if the hardware instance is replaced.

#### 2. BDNS Tag Syntax (asset.name)
The "BDNS Tag" refers to the **Device/Asset Role Name**. To ensure consistency and avoid ambiguity in digital building systems, the following syntax rules must be strictly followed:

**Format:** `X-Y` or `XZ-Y`

*   **`X` (Type Abbreviation)**: A 2 to 6 character uppercase alphabetical sequence. This abbreviation must be taken from the official *Building Device and Asset Abbreviation Registry*.
*   **`Y` (Building Unique Incremental Number)**: A variable-length integer that is unique to the building.
*   **`-` (Separator)**: A hyphen must be used to separate the type abbreviation and the incremental number.
*   **`Z` (Optional Asset Type Number)**: Used only if an `asset.type` definition is required.

#### 3. Strict Restrictions and Validation
When implementing or converting to BDNS tags, the following restrictions are mandatory:

*   **No Leading Zeros**: In the incremental numbers (`Y` and `Z`), **leading zeros are strictly prohibited** to avoid ambiguity (e.g., `DSSO-1` is valid, while `DSSO-00001` is invalid).
*   **Case Sensitivity**: Only **uppercase** alphabetic characters and numeric characters are allowed.
*   **Instance vs. Role Separation**: Data that includes machine-specific sequences or zero-padded serial numbers (like `DSSO-00001`) should be interpreted as **Instance Identifiers** rather than **BDNS Tags (Role Names)**. Proper BDNS tags must be explicitly defined using the semantic vocabulary of the Abbreviation Registry.

#### 4. Physical Labeling and Suffixes (Optional)
While the `asset.name` stored in the IFC data must strictly follow the syntax above, physical labels may optionally include a **suffix** (e.g., `asset.name_text`) to capture existing legacy tagging information or specific properties like floor levels. However, this suffix is not part of the core `asset.name` syntax used for digital identification.





### Output

The output is generated as RDF data serialized in Turtle format `.ttl`.

## How to use
To execute the converter, run the main script as follows.

```bash
python run.py
```

As part of the refactoring process, the execution flow is being simplified to rely on a single main run script together with a limited set of essential preprocessing modules.

## Project status
This project is under active development.

The initial implementation was organized around a highly individual development workflow, and the repository is currently being refactored and reorganized to improve clarity, reusability, and suitability for public release.

## License and acknowledgements
This work has been developed within the context of the SMART Building Data to OpenBIM Interoperability Project.

## Repository Structure

## Directory Descriptions