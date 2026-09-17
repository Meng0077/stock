"""工具共用参数模型；自动测试见 backend/tests/test_tool_params.py。"""

from pydantic import BaseModel, Field, ConfigDict

class CompanyToolParams(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        str_strip_whitespace=True,
        validate_assignment=True
    )

    company_id: str = Field(min_length=1, max_length=80)


class KnowledgeToolParams(CompanyToolParams):
    question: str = Field(min_length=1)
