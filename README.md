# MultiConvect

Multi-model convective forecast for Bulgaria combining ICON-EU, GFS, and ECMWF-IFS.

## Method

ICON-EU LPI is the leading model. GFS (REFC) and IFS (MUCAPE) confirm.

- **HIGH** — ICON + GFS + IFS agree
- **MED** — ICON + one other model
- **LOW** — ICON only, or GFS+IFS without ICON

## Install

```
conda create -n multiconvect python=3.11 -y
conda activate multiconvect
conda install -c conda-forge xarray cfgrib eccodes scipy numpy matplotlib=3.9 cartopy shapely pyyaml requests -y
pip install herbie-data
```

## Usage

```
python run.py --run 0
python run.py --run 0 --fxx 12
python run.py --date 2026-07-24 --run 0 --fxx 12
```

Output maps are saved in `output/maps/`.