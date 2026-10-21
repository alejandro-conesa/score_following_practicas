until curl -L -4 -C - --retry 5 --retry-all-errors \
  --speed-limit 50000 --speed-time 20 \
  -o data/msmd.zip \
  "https://zenodo.org/records/4745838/files/msmd.zip?download=1"; do
  echo "Reintentando..."; sleep 3
done