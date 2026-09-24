import ollama
import time

model_name = "qwen2.5-coder:14b"
prompt = "请用 Python 写一个快速排序算法。"

# 预热一次，避免冷启动影响
print("Warming up...")
ollama.generate(model=model_name, prompt="hello", options={"num_predict": 1})

print("Running speed test...")
response = ollama.generate(model=model_name, prompt=prompt)

# 从响应元数据中提取精确指标
eval_count = response.get("eval_count", 0)
eval_duration_ns = response.get("eval_duration", 1)

# 计算 tokens/s
tokens_per_second = eval_count / (eval_duration_ns / 1e9) if eval_duration_ns > 0 else 0

print(f"生成 token 数: {eval_count}")
print(f"生成耗时: {eval_duration_ns / 1e9:.2f} 秒")
print(f"**Token 速度: {tokens_per_second:.2f} tokens/s**")
