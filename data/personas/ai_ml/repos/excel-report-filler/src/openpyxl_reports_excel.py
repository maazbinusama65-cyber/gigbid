from openpyxl import load_workbook

def sync_excel(path, rows):
    wb = load_workbook(path)
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
