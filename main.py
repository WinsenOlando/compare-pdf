from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
import pdfplumber
import fitz
from io import BytesIO
from collections import defaultdict

app = FastAPI(title="Advanced PDF Compare API")

def extract_tables_dynamic(file_bytes):
    result = {}

    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            
            for table in tables:
                if not table:
                    continue

                header_idx = -1
                headers = []

                for i, row in enumerate(table):
                    clean_row = [str(cell).strip().replace('\n', ' ') if cell else "" for cell in row]
                    
                    if any("no" == str(t).lower() for t in clean_row):
                        header_idx = i
                        headers = clean_row
                        break

                if header_idx == -1:
                    continue

                col_count = len(headers)

                for i in range(header_idx + 1, len(table)):
                    row = table[i]
                    clean_row = [str(cell).strip().replace('\n', ' ') if cell else "" for cell in row]

                    if not any(clean_row):
                        continue

                    if len(clean_row) < col_count:
                        clean_row.extend([""] * (col_count - len(clean_row)))
                    elif len(clean_row) > col_count:
                        clean_row = clean_row[:col_count]

                    row_dict = dict(zip(headers, clean_row))

                    if "No" in row_dict and row_dict["No"].strip():
                        pk = row_dict["No"].strip()
                        result[pk] = {
                            "page": page_index,
                            "data": row_dict
                        }

    return result

def highlight_changes(compare_bytes, base_data, compare_data):
    doc = fitz.open(stream=compare_bytes, filetype="pdf")

    COLOR_GREEN = (0, 1, 0)
    COLOR_YELLOW = (1, 1, 0)
    COLOR_RED = (1, 0, 0)

    added = []
    changed = []
    removed = []

    for pk in compare_data:
        if pk not in base_data:
            added.append(pk)
        else:
            if base_data[pk]["data"] != compare_data[pk]["data"]:
                changed.append(pk)

    for pk in base_data:
        if pk not in compare_data:
            removed.append(pk)

    for pk in compare_data:
        page_index = compare_data[pk]["page"]
        page = doc[page_index]

        if pk in added:
            row_data = compare_data[pk]["data"]
            for value in row_data.values():
                text_instances = page.search_for(value)
                for inst in text_instances:
                    annot = page.add_highlight_annot(inst)
                    annot.set_colors(stroke=COLOR_GREEN)
                    annot.update()

        elif pk in changed:
            base_row = base_data[pk]["data"]
            compare_row = compare_data[pk]["data"]

            for column in compare_row:
                if column not in base_row:
                    continue

                if compare_row[column] != base_row[column]:
                    cell_text = compare_row[column]
                    cell_instances = page.search_for(cell_text)

                    for inst in cell_instances:
                        annot = page.add_highlight_annot(inst)
                        annot.set_colors(stroke=COLOR_YELLOW)
                        annot.update()

    if removed:
        summary = doc.new_page()
        y = 50
        summary.insert_text((50, y), "DATA DIHAPUS:", fontsize=14, color=COLOR_RED)
        y += 25

        for pk in removed:
            deleted_row_data = base_data[pk]["data"]
            row_text = " | ".join([f"{k}: {v}" for k, v in deleted_row_data.items()])
            
            summary.insert_text((60, y), f"[-] {row_text}", fontsize=10, color=COLOR_RED)
            y += 18

    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return output

@app.post("/api/v1/compare-pdf")
async def compare_pdf(
    pdf_pedoman: UploadFile = File(...),
    pdf_dibandingkan: UploadFile = File(...)
):
    try:
        base_bytes = await pdf_pedoman.read()
        compare_bytes = await pdf_dibandingkan.read()

        base_data = extract_tables_dynamic(base_bytes)
        compare_data = extract_tables_dynamic(compare_bytes)

        result_pdf = highlight_changes(compare_bytes, base_data, compare_data)

        return StreamingResponse(
            result_pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=hasil_compare.pdf"}
        )

    except Exception as e:
        return JSONResponse(
            content={"status": "error", "message": str(e)},
            status_code=500
        )