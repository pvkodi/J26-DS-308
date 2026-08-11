# 📊 Experimental Data Directory

This folder contains datasets, training labels, model configurations, and output logs.

> [!WARNING]
> Do not commit large binary datasets or database dumps to this repository. Use git ignore patterns or host datasets on shared cloud services, linking them in this directory.

## 📂 Subdirectory Layout

```
data/
├── raw/         # Unmodified, original datasets (excluded from Git tracking)
├── processed/   # Cleaned, structured, and preprocessed data (excluded from Git tracking)
└── metadata/    # Dataset metadata schemas, labels, and small config JSON/YAML files
```

## ⬇️ Data Sourcing

If you need to retrieve raw datasets:
1. Download files from [Insert Link to cloud storage/external source].
2. Extract the files and place them into the `data/raw/` subdirectory.
3. Run the preprocessing script inside `app/` to generate assets in `data/processed/`.
