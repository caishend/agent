"""报告生成工具。"""
from __future__ import annotations

import html
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.tools.base_tool import ArtifactItem, BaseTool, EvidenceItem, ToolContext, ToolInput, ToolResult
from app.config import settings


class ReportTool(BaseTool):
    name = "report"
    description = "将分析结论、风险评估和证据链整合为结构化 PDF 灾害评估报告。"

    def run(self, tool_input: ToolInput, context: ToolContext | None = None) -> ToolResult:
        params = tool_input.params or {}
        payload = self._build_payload(tool_input, context)
        output_path = self._resolve_output_path(params, context)

        report_format = output_path.suffix.lower().lstrip(".") or "pdf"

        try:
            if report_format == "docx":
                self._write_docx(output_path, payload)
            else:
                self._write_pdf(output_path, payload)
        except ImportError as exc:
            return self._failed(
                "报告生成失败：缺少 reportlab 依赖，请先安装 backend/requirements.txt。",
                "missing_dependency",
                error=str(exc),
            )
        except OSError as exc:
            return self._failed(f"报告生成失败：无法写入报告文件：{exc}", "write_failed", error=str(exc))

        artifacts = [ArtifactItem(type="report", path=str(output_path), metadata={"format": report_format})]
        metadata_path = self._write_metadata(output_path, payload)
        if metadata_path:
            artifacts.append(ArtifactItem(type="report_metadata", path=str(metadata_path), metadata={"format": "json"}))

        risk_text = payload["risk_level"]
        if payload.get("risk_score") is not None:
            risk_text = f"{risk_text}（{payload['risk_score']}）"

        return ToolResult(
            summary=f"【报告生成】已生成灾害评估报告：{output_path}；综合风险：{risk_text}",
            evidence=[
                EvidenceItem(
                    source="report",
                    type="generated_report",
                    content=f"报告《{payload['title']}》已生成，包含 {len(payload['evidence'])} 条证据和 {len(payload['suggestions'])} 条建议。",
                    confidence=0.95,
                    metadata={"path": str(output_path)},
                )
            ],
            artifacts=artifacts,
            confidence=0.95,
            data={
                "report_status": "generated",
                "report_path": str(output_path),
                "metadata_path": str(metadata_path) if metadata_path else None,
                "title": payload["title"],
                "risk_level": payload["risk_level"],
                "risk_score": payload.get("risk_score"),
                "evidence_count": len(payload["evidence"]),
                "format": report_format,
            },
        )

    def _build_payload(self, tool_input: ToolInput, context: ToolContext | None) -> dict[str, Any]:
        params = tool_input.params or {}
        task = self._as_dict(params.get("task") or params.get("task_document"))
        analysis = self._as_dict(
            params.get("risk_assessment") or params.get("analysis_result") or params.get("risk_result")
        )

        task_id = params.get("task_id") or task.get("task_id") or (context.task_id if context else None)
        title = str(params.get("title") or f"SkyGuard 灾害影响评估报告{f' - 任务 {task_id}' if task_id else ''}")
        disaster_type = str(params.get("disaster_type") or task.get("disaster_type") or "未指定")
        location = str(params.get("location") or task.get("location") or "未指定")
        summary = str(
            params.get("summary")
            or analysis.get("summary")
            or task.get("conversation_summary")
            or tool_input.query
            or "系统根据已确认任务信息、风险评估结果和证据链生成本报告。"
        )

        risk_score = params.get("risk_score", analysis.get("risk_score"))
        risk_level = str(params.get("risk_level") or analysis.get("risk_level") or "待评估")

        known_info = self._as_list(params.get("known_info") or task.get("known_info"))
        missing_info = self._as_list(params.get("missing_info") or task.get("missing_info"))
        reasons = self._as_list(params.get("reasons") or analysis.get("reason") or analysis.get("reasons"))
        suggestions = self._as_list(params.get("suggestions") or analysis.get("suggestion") or analysis.get("suggestions"))
        if not suggestions:
            suggestions = ["请结合现场核验、气象更新和应急部门要求，对本报告结论进行复核后再执行。"]

        return {
            "title": title,
            "task_id": task_id,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "disaster_type": disaster_type,
            "location": location,
            "summary": summary,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "known_info": known_info,
            "missing_info": missing_info,
            "reasons": reasons,
            "suggestions": suggestions,
            "evidence": self._collect_evidence(params),
            "artifacts": self._collect_artifacts(params),
            "references": self._as_list(params.get("references")),
        }

    def _write_pdf(self, output_path: Path, payload: dict[str, Any]) -> None:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        output_path.parent.mkdir(parents=True, exist_ok=True)
        font_name = "STSong-Light"
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        except Exception:
            font_name = "Helvetica"

        styles = getSampleStyleSheet()
        normal = ParagraphStyle(
            "SkyGuardNormal",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
            wordWrap="CJK",
        )
        title = ParagraphStyle(
            "SkyGuardTitle",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=20,
            leading=28,
            spaceAfter=10,
            wordWrap="CJK",
        )
        heading = ParagraphStyle(
            "SkyGuardHeading",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=14,
            leading=20,
            spaceBefore=8,
            spaceAfter=6,
            wordWrap="CJK",
        )

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=16 * mm,
            title=payload["title"],
        )

        story: list[Any] = [
            Paragraph(self._escape(payload["title"]), title),
            Paragraph(f"生成时间：{self._escape(payload['generated_at'])}", normal),
            Spacer(1, 8),
        ]

        story.extend(
            self._table(
                [
                    ["任务 ID", payload.get("task_id") or "-"],
                    ["灾害类型", payload["disaster_type"]],
                    ["目标区域", payload["location"]],
                    ["综合风险", self._risk_text(payload)],
                ],
                normal,
                colors,
            )
        )

        self._add_section(story, "1. 摘要", payload["summary"], heading, normal)
        self._add_list_section(story, "2. 已确认信息", payload["known_info"], heading, normal, empty="暂无已确认信息。")
        self._add_list_section(story, "3. 缺失信息与待核验假设", payload["missing_info"], heading, normal, empty="暂无缺失信息。")
        self._add_list_section(story, "4. 综合风险原因", payload["reasons"], heading, normal, empty="暂无结构化风险原因。")
        self._add_list_section(story, "5. 应急响应建议", payload["suggestions"], heading, normal)
        self._add_evidence_section(story, payload["evidence"], heading, normal, colors)
        self._add_list_section(story, "7. 参考资料", payload["references"], heading, normal, empty="暂无参考资料。")

        footer = lambda canvas, doc_: self._footer(canvas, doc_, font_name)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)

    def _write_docx(self, output_path: Path, payload: dict[str, Any]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        paragraphs = [
            payload["title"],
            f"生成时间：{payload['generated_at']}",
            f"任务 ID：{payload.get('task_id') or '-'}",
            f"灾害类型：{payload['disaster_type']}",
            f"目标区域：{payload['location']}",
            f"综合风险：{self._risk_text(payload)}",
            "",
            "1. 摘要",
            payload["summary"],
            "",
            "2. 已确认信息",
            *self._numbered_lines(payload["known_info"], "暂无已确认信息。"),
            "",
            "3. 缺失信息与待核验假设",
            *self._numbered_lines(payload["missing_info"], "暂无缺失信息。"),
            "",
            "4. 综合风险原因",
            *self._numbered_lines(payload["reasons"], "暂无结构化风险原因。"),
            "",
            "5. 应急响应建议",
            *self._numbered_lines(payload["suggestions"], "暂无建议。"),
            "",
            "6. 证据链附录",
            *self._evidence_lines(payload["evidence"]),
            "",
            "7. 图片与文件产物",
            *self._artifact_lines(payload["artifacts"]),
            "",
            "8. 参考资料",
            *self._numbered_lines(payload["references"], "暂无参考资料。"),
        ]

        image_paths = self._docx_image_paths(payload["artifacts"])
        image_relationships = {
            path: {
                "rid": f"rIdImage{index}",
                "target": f"media/image{index}{path.suffix.lower()}",
            }
            for index, path in enumerate(image_paths, start=1)
        }
        document_xml = self._docx_document_xml(paragraphs, image_relationships)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
            )
            archive.writestr(
                "_rels/.rels",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
            )
            archive.writestr("word/document.xml", document_xml)
            archive.writestr("word/_rels/document.xml.rels", self._docx_relationships_xml(image_relationships))
            for path, relation in image_relationships.items():
                archive.writestr(f"word/{relation['target']}", path.read_bytes())
            archive.writestr(
                "docProps/core.xml",
                f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{self._xml_escape(payload["title"])}</dc:title>
  <dc:creator>SkyGuard</dc:creator>
  <cp:lastModifiedBy>SkyGuard Agent</cp:lastModifiedBy>
</cp:coreProperties>""",
            )
            archive.writestr(
                "docProps/app.xml",
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>SkyGuard</Application>
</Properties>""",
            )

    def _table(self, rows: list[list[Any]], normal: Any, colors: Any) -> list[Any]:
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        table = Table(
            [[Paragraph(self._escape(str(key)), normal), Paragraph(self._escape(str(value)), normal)] for key, value in rows],
            colWidths=[90, 360],
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c2cc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return [table, Spacer(1, 8)]

    def _add_section(self, story: list[Any], title: str, text: str, heading: Any, normal: Any) -> None:
        from reportlab.platypus import Paragraph, Spacer

        story.append(Paragraph(self._escape(title), heading))
        story.append(Paragraph(self._escape(text), normal))
        story.append(Spacer(1, 6))

    def _add_list_section(
        self,
        story: list[Any],
        title: str,
        items: list[Any],
        heading: Any,
        normal: Any,
        empty: str = "暂无。",
    ) -> None:
        from reportlab.platypus import Paragraph, Spacer

        story.append(Paragraph(self._escape(title), heading))
        if not items:
            story.append(Paragraph(self._escape(empty), normal))
        for index, item in enumerate(items, start=1):
            story.append(Paragraph(self._escape(f"{index}. {item}"), normal))
        story.append(Spacer(1, 6))

    def _add_evidence_section(self, story: list[Any], evidence: list[dict[str, Any]], heading: Any, normal: Any, colors: Any) -> None:
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        story.append(Paragraph("6. 证据链附录", heading))
        if not evidence:
            story.append(Paragraph("暂无证据链。", normal))
            return

        rows = [[Paragraph("来源", normal), Paragraph("类型", normal), Paragraph("内容", normal), Paragraph("置信度", normal)]]
        for item in evidence:
            rows.append(
                [
                    Paragraph(self._escape(str(item.get("source", "-"))), normal),
                    Paragraph(self._escape(str(item.get("type", "-"))), normal),
                    Paragraph(self._escape(str(item.get("content", "-"))[:500]), normal),
                    Paragraph(self._escape(self._format_confidence(item.get("confidence"))), normal),
                ]
            )

        table = Table(rows, colWidths=[80, 80, 230, 60], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfeaf3")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c2cc")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 6))

    def _footer(self, canvas: Any, doc: Any, font_name: str) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 9)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 10 * 1.0, f"SkyGuard | 第 {doc.page} 页")
        canvas.restoreState()

    def _resolve_output_path(self, params: dict[str, Any], context: ToolContext | None) -> Path:
        report_format = str(params.get("format") or params.get("report_format") or "pdf").lower().lstrip(".")
        if report_format not in {"pdf", "docx"}:
            report_format = "pdf"

        raw_path = params.get("output_path") or params.get("report_path")
        if raw_path:
            path = Path(str(raw_path)).expanduser()
            if path.suffix.lower() != f".{report_format}":
                path = path.with_suffix(f".{report_format}")
            return path

        task_id = params.get("task_id") or (context.task_id if context else None) or "unknown"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path(settings.REPORT_DIR) / f"task_{task_id}_{timestamp}.{report_format}"

    def _numbered_lines(self, items: list[Any], empty: str) -> list[str]:
        if not items:
            return [empty]
        return [f"{index}. {item}" for index, item in enumerate(items, start=1)]

    def _evidence_lines(self, evidence: list[dict[str, Any]]) -> list[str]:
        if not evidence:
            return ["暂无证据链。"]
        lines = []
        for index, item in enumerate(evidence, start=1):
            source = item.get("source", "-")
            content = str(item.get("content", "-"))[:500]
            confidence = self._format_confidence(item.get("confidence"))
            lines.append(f"{index}. 来源：{source}；置信度：{confidence}；内容：{content}")
        return lines

    def _artifact_lines(self, artifacts: list[dict[str, Any]]) -> list[str]:
        if not artifacts:
            return ["暂无图片、截图或文件产物。"]
        lines = []
        for index, item in enumerate(artifacts, start=1):
            artifact_type = item.get("type", "file")
            path = item.get("path", "-")
            description = self._as_dict(item.get("metadata")).get("description") or self._as_dict(item.get("metadata")).get("url") or ""
            lines.append(f"{index}. 类型：{artifact_type}；路径：{path}{f'；说明：{description}' if description else ''}")
        return lines

    def _docx_document_xml(self, paragraphs: list[str], image_relationships: dict[Path, dict[str, str]]) -> str:
        body = "\n".join(self._docx_paragraph(text) for text in paragraphs)
        if image_relationships:
            body += "\n" + "\n".join(
                self._docx_image_paragraph(path, relation["rid"]) for path, relation in image_relationships.items()
            )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
  <w:body>
    {body}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>
    </w:sectPr>
  </w:body>
</w:document>"""

    def _docx_paragraph(self, text: Any) -> str:
        return f"<w:p><w:r><w:t xml:space=\"preserve\">{self._xml_escape(text)}</w:t></w:r></w:p>"

    def _docx_image_paragraph(self, path: Path, relationship_id: str) -> str:
        cx, cy = self._image_size_emu(path)
        name = self._xml_escape(path.name)
        return f"""
<w:p>
  <w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="{cx}" cy="{cy}"/>
        <wp:docPr id="1" name="{name}"/>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr><pic:cNvPr id="0" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>
              <pic:blipFill><a:blip r:embed="{relationship_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
              <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:p>"""

    def _docx_relationships_xml(self, image_relationships: dict[Path, dict[str, str]]) -> str:
        relationships = "\n".join(
            f'  <Relationship Id="{relation["rid"]}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{relation["target"]}"/>'
            for relation in image_relationships.values()
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{relationships}
</Relationships>"""

    def _docx_image_paths(self, artifacts: list[dict[str, Any]]) -> list[Path]:
        paths: list[Path] = []
        for artifact in artifacts:
            raw_path = artifact.get("path")
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                continue
            if path.exists() and path.is_file():
                paths.append(path)
        return list(dict.fromkeys(paths))

    def _image_size_emu(self, path: Path) -> tuple[int, int]:
        max_width_emu = 5_300_000
        try:
            from PIL import Image

            with Image.open(path) as image:
                width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("invalid image size")
            aspect = height / width
            return max_width_emu, int(max_width_emu * aspect)
        except Exception:
            return max_width_emu, 3_000_000

    def _xml_escape(self, value: Any) -> str:
        return html.escape(str(value if value is not None else ""), quote=True)

    def _write_metadata(self, output_path: Path, payload: dict[str, Any]) -> Path | None:
        metadata_path = output_path.with_suffix(".json")
        try:
            metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            return None
        return metadata_path

    def _collect_evidence(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items: list[Any] = []
        for key in ("evidence", "candidate_evidence"):
            raw_items.extend(self._as_list(params.get(key)))

        tool_results = self._as_dict(params.get("tool_results"))
        for tool_name, result in tool_results.items():
            result_dict = self._as_dict(result)
            raw_items.extend(self._as_list(result_dict.get("evidence")))
            if result_dict.get("summary"):
                raw_items.append(
                    {
                        "source": tool_name,
                        "type": "tool_summary",
                        "content": result_dict["summary"],
                        "confidence": result_dict.get("confidence"),
                    }
                )

        normalized = [self._normalize_evidence(item) for item in raw_items]
        return [item for item in normalized if item["content"]]

    def _collect_artifacts(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        artifacts = []
        for item in self._as_list(params.get("artifacts")):
            if isinstance(item, dict):
                artifacts.append(item)
            else:
                artifacts.append({"type": "file", "path": str(item)})
        return artifacts

    def _normalize_evidence(self, item: Any) -> dict[str, Any]:
        if isinstance(item, EvidenceItem):
            return {
                "source": item.source,
                "type": item.type,
                "content": item.content,
                "confidence": item.confidence,
                "metadata": item.metadata,
            }
        if isinstance(item, dict):
            return {
                "source": str(item.get("source") or "unknown"),
                "type": str(item.get("type") or "evidence"),
                "content": str(item.get("content") or item.get("summary") or ""),
                "confidence": item.get("confidence"),
                "metadata": self._as_dict(item.get("metadata")),
            }
        return {"source": "manual", "type": "text", "content": str(item), "confidence": None, "metadata": {}}

    def _risk_text(self, payload: dict[str, Any]) -> str:
        if payload.get("risk_score") is None:
            return str(payload["risk_level"])
        return f"{payload['risk_level']} / {payload['risk_score']}"

    def _format_confidence(self, value: Any) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return "-"

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "__dict__") and not isinstance(value, type):
            return dict(value.__dict__)
        return value if isinstance(value, dict) else {}

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, (tuple, set)):
            return list(value)
        return [value]

    def _escape(self, value: Any) -> str:
        text = str(value if value is not None else "")
        return html.escape(text).replace("\n", "<br/>")

    def _failed(self, summary: str, reason: str, **extra: Any) -> ToolResult:
        return ToolResult(
            summary=summary,
            confidence=0.0,
            data={"report_status": "failed", "reason": reason, **extra},
        )
