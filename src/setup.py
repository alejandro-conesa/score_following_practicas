import os
import urllib.request
import zipfile

DATA_PATH = "./data/msmd.zip"
DATA_URL = "https://zenodo.org/record/4745838/files/msmd.zip?download=1"


def main():
    if os.path.exists(DATA_PATH):
        return

    data_dir = os.path.dirname(DATA_PATH)
    os.makedirs(data_dir, exist_ok=True)

    print(f"Downloading data to {DATA_PATH} ...")
    urllib.request.urlretrieve(DATA_URL, DATA_PATH)

    print(f"Extracting data {DATA_PATH} ...")
    with zipfile.ZipFile(DATA_PATH, "r") as zip_ref:
        zip_ref.extractall(data_dir)

    os.unlink(DATA_PATH)


if __name__ == "__main__":
    main()