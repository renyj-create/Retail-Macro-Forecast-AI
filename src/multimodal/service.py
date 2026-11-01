import hashlib
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pydantic import ValidationError
from .schemas import AnalysisResponse, Evidence, Extraction, ValidatedField, Issue
from .vision_client import VisionTimeout

ALLOWED = {'date','revenue','profit','margin_pct','transactions'}

def validate_fields(extraction):
    fields, issues, seen = [], [], set()
    for field in extraction.fields:
        value, unit, status = None, None, 'valid'
        code = None
        if field.name not in ALLOWED: code='unknown_field'
        elif field.name in seen: code='duplicate_field'
        elif field.raw_text is None or not field.raw_text.strip(): code='missing_value'
        elif field.name == 'date':
            try:
                raw = field.raw_text.strip()
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw): raise ValueError()
                value = date.fromisoformat(raw).isoformat()
                if field.unit not in (None, '', 'date'): code='unit_invalid'
            except ValueError: code='invalid_date'
        else:
            try:
                raw = field.raw_text.strip()
                number = Decimal(raw)
                if not number.is_finite(): code='nonfinite_number'
                elif not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', raw): code='invalid_number'
                elif field.name in ('revenue','profit'):
                    factors={'元':Decimal(1),'万元':Decimal(10000),'亿元':Decimal(100000000)}
                    if field.unit not in factors: code='unit_invalid'
                    else: value=format(number*factors[field.unit], 'f'); unit='元'
                elif field.name == 'margin_pct':
                    if field.unit != '%': code='unit_invalid'
                    elif not -100 <= number <= 100: code='out_of_range'
                    else: value=format(number, 'f'); unit='%'
                else:
                    if field.unit != '笔': code='unit_invalid'
                    elif number < 0 or number != number.to_integral_value(): code='out_of_range'
                    else: value=format(number, 'f'); unit='笔'
            except (InvalidOperation, ValueError): code='invalid_number'
        seen.add(field.name)
        if code:
            value,unit,status=None,None,('missing' if code=='missing_value' else 'invalid')
            issues.append(Issue(field=field.name, code=code, message='字段缺失或不满足字段、日期、数值及单位契约，请核实原图'))
        fields.append(ValidatedField(**field.model_dump(), normalized_value=value,normalized_unit=unit,validation_status=status))
    for name in ('date','revenue'):
        if name not in seen:
            fields.append(ValidatedField(name=name,validation_status='missing'))
            issues.append(Issue(field=name,code='required_field_missing',message='经营报表必填字段未识别，请核实原图'))
    if extraction.document_type == 'unknown':
        issues.append(Issue(field='document_type',code='unsupported_document',message='未识别为经营报表'))
    return fields,issues

def analyze(image, question, client):
    mock=bool(client and client.is_mock)
    result=AnalysisResponse(task_id=uuid.uuid4().hex,status='not_configured',provider=client.provider if client else 'none',is_mock=mock,
        evidence=Evidence(evidence_id=uuid.uuid4().hex,data_nature='simulated' if mock else 'user_uploaded_unverified',source_sha256=hashlib.sha256(image.content).hexdigest()))
    if client is None:
        result.error_code='vision_not_configured';result.message='视觉模型未配置，未执行识别';return result
    try:
        output=client.extract(image,question)
        if not isinstance(output,str) or len(output)>65536: raise ValueError()
        raw=json.loads(output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        extraction=Extraction.model_validate(raw)
    except (VisionTimeout, TimeoutError):
        result.status='failed';result.error_code='vision_timeout';result.message='视觉服务超时，请稍后重试';return result
    except (ValidationError,ValueError,TypeError):
        result.status='failed';result.error_code='invalid_model_output';result.message='视觉输出不符合结构契约';return result
    except Exception:
        result.status='failed';result.error_code='vision_service_error';result.message='视觉服务调用失败';return result
    result.document_type=extraction.document_type
    result.fields,result.issues=validate_fields(extraction)
    result.status='mock' if mock else ('needs_review' if result.issues else 'success')
    result.message='模拟识别，仅用于开发测试' if mock else '识别完成，内容未经核实；校验通过不代表图片内容真实'
    lines=['来源：image_extraction；'+('模拟数据，非真实识别' if mock else '用户上传，未经核实'),
           '报告方式：确定性模板，未调用报告大模型。', '证据 ID：'+result.evidence.evidence_id]
    for field in result.fields:
        lines.append(field.name+'：'+(field.normalized_value+' '+(field.normalized_unit or '') if field.validation_status=='valid' else '无法确认，请核实原图'))
    lines.append('校验问题：'+str(len(result.issues))+' 项。以上不构成数据库事实或经营预测。')
    result.report='\n'.join(lines);result.report_status='template'
    return result
