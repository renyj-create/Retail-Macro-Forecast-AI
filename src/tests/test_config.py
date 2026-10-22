# src/tests/test_config.py
"""
DeepSeek 配置与降级提示测试。

不发起真实 API 调用、不读取真实 .env 密钥、不打印任何密钥；
验证缺少 DeepSeek API Key 时给出清晰提示，并防止旧 DashScope/Qwen 依赖回潮。
"""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import src.agents.graph_workflow as gw


class TestDeepSeekConfig(unittest.TestCase):

    def test_missing_api_key_raises_clear_error(self):
        """client 为 None（未配置 DEEPSEEK_API_KEY）时，_llm_chat 应抛出明确错误。"""
        saved = gw.client
        gw.client = None
        try:
            with self.assertRaises(RuntimeError) as ctx:
                gw._llm_chat("你是助手", "测试问题")
            # 错误信息应明确指向 DeepSeek 的 API Key，便于用户排查
            self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))
        finally:
            gw.client = saved

    def test_missing_api_key_classified_as_not_configured(self):
        """缺少密钥类异常应归类为「未配置 API Key」，供前端如实展示。"""
        self.assertEqual(
            gw.classify_llm_error(RuntimeError("未配置 DEEPSEEK_API_KEY，大模型不可用")),
            "未配置 API Key",
        )
        self.assertEqual(
            gw.classify_llm_error(RuntimeError("deepseek_api_key missing")),
            "未配置 API Key",
        )

    def test_auth_failure_classified(self):
        """401 鉴权失败应归类为「API Key 无效或鉴权失败」。"""
        self.assertEqual(
            gw.classify_llm_error(RuntimeError("401 Unauthorized")),
            "API Key 无效或鉴权失败",
        )

    def test_module_reads_deepseek_env_vars(self):
        """配置项必须来自 DeepSeek 环境变量，而非旧 DashScope/Qwen 变量。"""
        # 模块在导入时已把配置读取到模块级常量；这里校验键名/默认值来源。
        self.assertIsInstance(gw.MODEL_NAME, str)
        self.assertIsInstance(gw.BASE_URL, str)
        # 默认模型名不得再指向 Qwen
        self.assertNotIn("qwen", gw.MODEL_NAME.lower())

    def test_no_dashscope_residual_in_module_source(self):
        """graph_workflow.py 源码中不应残留 DashScope/Qwen 强依赖。"""
        with open(gw.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        lower = source.lower()
        for forbidden in ("dashscope_api_key", "dashscope.aliyuncs.com",
                          "qwen_model", "qwen3"):
            self.assertNotIn(forbidden, lower)


if __name__ == "__main__":
    unittest.main()
