Write-Host "Starting EU VAT Hub API on port 8503..."
Start-Process powershell -ArgumentList "-NoExit -Command `"C:\v\Scripts\Activate.ps1; cd eu_vat_hub; uvicorn api:app --port 8503`""

Write-Host "Starting EU VAT Hub Dashboard on port 8502..."
Start-Process powershell -ArgumentList "-NoExit -Command `"C:\v\Scripts\Activate.ps1; cd eu_vat_hub; streamlit run app.py --server.port 8502`""

Write-Host "Starting Ireland VAT App on port 8501..."
Start-Process powershell -ArgumentList "-NoExit -Command `"C:\v\Scripts\Activate.ps1; streamlit run app.py --server.port 8501`""

Write-Host "All applications have been launched in separate terminal windows."
