"""
gee_mock.py — Google Earth Engine mock for offline development and testing.

Simulates:
  - Image collection (10-50 images)
  - Per-image metadata (date, cloud cover, source)
  - Spatiotemporal filtering (date range, cloud threshold)
  - Time series extraction over a region

Usage:
    python tools/gee_mock.py
"""

import math
import random
import statistics
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SENSOR_SOURCES = ["Landsat-8", "Landsat-9", "Sentinel-2A", "Sentinel-2B"]
BAND_NAMES = ["B1", "B2", "B3", "B4", "B5", "B6", "B7"]

# Default region of interest (Landsat tile in decimal degrees)
DEFAULT_REGION = {
    "type": "Polygon",
    "coordinates": [[
        [120.0, 30.0],
        [121.0, 30.0],
        [121.0, 31.0],
        [120.0, 31.0],
        [120.0, 30.0]
    ]]
}

# Seeded RNG for deterministic output
_rng = random.Random(42)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pixel_value(base, row, col, noise=0.05):
    """Generate a spatially coherent pixel value with noise."""
    trend = 0.3 * math.sin(row / 10) + 0.2 * math.cos(col / 8)
    return round(base + trend + _rng.uniform(-noise, noise), 4)


def _make_grid(rows=20, cols=20, base=0.5):
    """Generate a 2-D grid of pixel values."""
    return [[_pixel_value(base, r, c) for c in range(cols)] for r in range(rows)]


# ---------------------------------------------------------------------------
# Image  — simulates ee.Image
# ---------------------------------------------------------------------------

class Image:
    """A single raster image with properties and pixel data."""

    def __init__(self, image_id, date, cloud_cover, source, bands=None):
        self.id = image_id
        self._properties = {
            "id": image_id,
            "date": date,
            "cloud_cover": cloud_cover,
            "source": source,
            "year": date.year,
            "month": date.month,
            "doy": date.timetuple().tm_yday,
        }
        self._bands = bands or {
            name: _make_grid(base=0.3 + 0.5 * _rng.random())
            for name in BAND_NAMES
        }

    # -- Properties ---------------------------------------------------------

    def get(self, key):
        """Get a property value by name."""
        return self._properties.get(key)

    @property
    def properties(self):
        """Return dict of all properties (read-only view)."""
        return dict(self._properties)

    @property
    def date(self):
        return self._properties["date"]

    @property
    def cloud_cover(self):
        return self._properties["cloud_cover"]

    # -- Pixel operations ---------------------------------------------------

    def sample(self, band="B4", x=10, y=10):
        """Get a single pixel value at (row=y, col=x) in a given band."""
        band_data = self._bands.get(band)
        if band_data is None:
            raise KeyError(f"Band '{band}' not found. Available: {list(self._bands)}")
        return band_data[y % len(band_data)][x % len(band_data[0])]

    def sample_region(self, band="B4", region=None):
        """Get all pixel values for a band (simulated region sampling)."""
        band_data = self._bands.get(band)
        if band_data is None:
            raise KeyError(f"Band '{band}' not found.")
        return [v for row in band_data for v in row]

    def reduce_region(self, reducer="mean", band="B4"):
        """Reduce a band over the whole image (mean / median / max / min)."""
        values = self.sample_region(band)
        if reducer == "mean":
            return statistics.mean(values)
        elif reducer == "median":
            return statistics.median(values)
        elif reducer == "max":
            return max(values)
        elif reducer == "min":
            return min(values)
        else:
            raise ValueError(f"Unknown reducer: {reducer}")

    # -- Display ------------------------------------------------------------

    def __repr__(self):
        return (f"Image({self.id}, {self.date.date()}, "
                f"cloud={self.cloud_cover:.0%}, {self.properties['source']})")


# ---------------------------------------------------------------------------
# ImageCollection  — simulates ee.ImageCollection
# ---------------------------------------------------------------------------

class ImageCollection:
    """An ordered collection of Image objects with Earth Engine–like filtering."""

    def __init__(self, images=None):
        self._images = images or []

    # -- Construction helpers -----------------------------------------------

    @classmethod
    def generate(cls, count=30, start_date="2024-01-01", interval_days=16):
        """
        Generate a simulated ImageCollection.

        Parameters
        ----------
        count : int
            Number of images (10-50).
        start_date : str
            ISO date string for the first image.
        interval_days : int
            Days between consecutive acquisitions (Landsat repeats ≈ 16).
        """
        if not 10 <= count <= 50:
            raise ValueError(f"count must be 10-50, got {count}")

        start = datetime.strptime(start_date, "%Y-%m-%d")
        images = []

        for i in range(count):
            img_date = start + timedelta(days=interval_days * i)
            cloud = _rng.uniform(0.0, 0.8)
            source = _rng.choice(SENSOR_SOURCES)
            img_id = f"{source.replace('-', '')}_{img_date.strftime('%Y%m%d')}_{i:02d}"
            images.append(Image(img_id, img_date, cloud, source))

        return cls(images)

    # -- Filtering ----------------------------------------------------------

    def filter_date(self, start, end):
        """
        Filter images within a date range [start, end).

        Parameters
        ----------
        start, end : str or datetime
            ISO date strings or datetime objects.
        """
        if isinstance(start, str):
            start = datetime.strptime(start, "%Y-%m-%d")
        if isinstance(end, str):
            end = datetime.strptime(end, "%Y-%m-%d")

        filtered = [img for img in self._images if start <= img.date < end]
        return ImageCollection(filtered)

    def filter_cloud(self, threshold=0.3):
        """
        Filter images with cloud_cover <= threshold.

        Parameters
        ----------
        threshold : float
            Maximum allowable cloud cover fraction.
        """
        filtered = [img for img in self._images if img.cloud_cover <= threshold]
        return ImageCollection(filtered)

    def filter_property(self, key, value):
        """Filter images where a property exactly matches a value."""
        filtered = [img for img in self._images if img.get(key) == value]
        return ImageCollection(filtered)

    # -- Sequence operations ------------------------------------------------

    def limit(self, n):
        """Return first N images."""
        return ImageCollection(self._images[:n])

    def sort(self, key="date", ascending=True):
        """Sort images by a property."""
        sorted_imgs = sorted(self._images, key=lambda img: img.get(key) or 0,
                             reverse=not ascending)
        return ImageCollection(sorted_imgs)

    def to_list(self):
        """Return plain list of Image objects."""
        return list(self._images)

    @property
    def size(self):
        """Number of images in the collection."""
        return len(self._images)

    def first(self):
        """Return the first image."""
        if not self._images:
            raise IndexError("Empty ImageCollection")
        return self._images[0]

    # -- Time series --------------------------------------------------------

    def get_time_series(self, band="B4", reducer="mean"):
        """
        Extract a time series of reduced values across the collection.

        Returns
        -------
        list of (datetime, float) tuples, one per image, sorted by date.
        """
        sorted_imgs = sorted(self._images, key=lambda img: img.date)
        series = []
        for img in sorted_imgs:
            val = img.reduce_region(reducer, band)
            series.append((img.date, val))
        return series

    def get_cloud_free_series(self, band="B4", reducer="mean", cloud_max=0.1):
        """
        Time series filtered to near-cloud-free images only.
        Useful for plotting clear-sky vegetation trends.
        """
        clean = self.filter_cloud(cloud_max)
        return clean.get_time_series(band, reducer)

    # -- Aggregation --------------------------------------------------------

    def aggregate_stats(self):
        """Return summary statistics of cloud cover across the collection."""
        clouds = [img.cloud_cover for img in self._images]
        if not clouds:
            return {}
        return {
            "count": len(clouds),
            "min_cloud": round(min(clouds), 3),
            "max_cloud": round(max(clouds), 3),
            "mean_cloud": round(statistics.mean(clouds), 3),
            "median_cloud": round(statistics.median(clouds), 3),
            "std_cloud": round(statistics.stdev(clouds), 3) if len(clouds) > 1 else 0,
        }

    def date_range(self):
        """Return (earliest_date, latest_date) tuple."""
        if not self._images:
            return (None, None)
        dates = [img.date for img in self._images]
        return (min(dates), max(dates))

    # -- Display ------------------------------------------------------------

    def __repr__(self):
        return f"ImageCollection({self.size} images)"

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        return self._images[idx]


# ---------------------------------------------------------------------------
# Test / demonstration
# ---------------------------------------------------------------------------

def test():
    """
    Run a full demonstration of the mock GEE functionality.

    Exercises:
      1. Collection generation (30 images)
      2. Per-image metadata inspection
      3. Date-range filtering
      4. Cloud-cover filtering
      5. Sorted listing
      6. Time series extraction (full vs cloud-free)
      7. Aggregation statistics
      8. Chained filtering pipeline
    """
    print("=" * 60)
    print("gee_mock.py — Test Suite")
    print("=" * 60)

    # ---- 1. Generate collection -------------------------------------------
    print("\n[1] Generating 30-image collection (Landsat/Sentinel simulation)")
    col = ImageCollection.generate(count=30, start_date="2024-01-01", interval_days=16)
    print(f"    Created: {col}")
    print(f"    Date range: {col.date_range()[0].date()} → {col.date_range()[1].date()}")

    # ---- 2. Inspect individual image --------------------------------------
    print("\n[2] Inspecting first image")
    first = col.first()
    print(f"    {first}")
    for k, v in first.properties.items():
        print(f"      {k}: {v}")

    # ---- 3. Filter by date ------------------------------------------------
    print("\n[3] Filter by date: 2024-04-01 → 2024-10-01")
    q2 = col.filter_date("2024-04-01", "2024-10-01")
    print(f"    Q2 images: {q2.size}")

    # ---- 4. Filter by cloud -----------------------------------------------
    print("\n[4] Filter cloud ≤ 20%")
    clear = col.filter_cloud(0.2)
    print(f"    Clear images: {clear.size} / {col.size}")

    # ---- 5. Sorted listing ------------------------------------------------
    print("\n[5] 5 clearest images (sorted by cloud cover ascending)")
    clearest = col.sort("cloud_cover", ascending=True).limit(5)
    for img in clearest.to_list():
        print(f"    {img}")

    # ---- 6. Time series ---------------------------------------------------
    print("\n[6] Time series — mean B4 (red band) over all 30 images")
    series = col.get_time_series(band="B4", reducer="mean")
    print(f"    {len(series)} data points")
    for dt, val in series[:5]:
        print(f"      {dt.date()}  {val:.4f}")
    print("      ...")

    print("\n[7] Cloud-free time series (cloud ≤ 10%)")
    clean_series = col.get_cloud_free_series(band="B4", reducer="mean", cloud_max=0.1)
    print(f"    {len(clean_series)} data points (filtered from {col.size})")
    for dt, val in clean_series[:5]:
        print(f"      {dt.date()}  {val:.4f}")
    if len(clean_series) > 5:
        print("      ...")

    # ---- 7. Aggregation ---------------------------------------------------
    print("\n[8] Cloud cover statistics across collection")
    stats = col.aggregate_stats()
    for k, v in stats.items():
        print(f"    {k}: {v}")

    # ---- 8. Chained pipeline ----------------------------------------------
    print("\n[9] Chained pipeline: filter_date → filter_cloud → sort")
    pipeline = (
        col
        .filter_date("2024-06-01", "2024-12-31")
        .filter_cloud(0.3)
        .sort("date", ascending=True)
    )
    print(f"    Pipeline result: {pipeline.size} images")
    for img in pipeline.to_list():
        print(f"      {img}")

    # ---- 9. Single-pixel sample -------------------------------------------
    print("\n[10] Single-pixel sample (first image, band B4, row=5, col=8)")
    pixel = first.sample(band="B4", x=8, y=5)
    print(f"    Value: {pixel}")

    # ---- 10. Region reduction ---------------------------------------------
    print("\n[11] Region reduction (first image, band B5=NIR)")
    for reducer in ("mean", "median", "max", "min"):
        val = first.reduce_region(reducer=reducer, band="B5")
        print(f"    B5 {reducer}: {val:.4f}")

    # ---- Summary ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    test()
