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