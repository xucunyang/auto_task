import ollama
import time

model_name = "qwen2.5-coder:14b"
prompt = "请用 Python 写一个快速排序算法。"
num_tests = 5

# 预热一次，避免冷启动影响
print("Warming up...")
ollama.generate(model=model_name, prompt="hello", options={"num_predict": 1})

print("Running speed test...")
total_eval_count = 0
total_eval_duration_ns = 0

for i in range(num_tests):
    response = ollama.generate(model=model_name, prompt=prompt)

    # 从响应元数据中提取精确指标
    eval_count = response.get("eval_count", 0)
    eval_duration_ns = response.get("eval_duration", 1)

    total_eval_count += eval_count
    total_eval_duration_ns += eval_duration_ns

# 计算平均值
average_eval_duration_ns = total_eval_duration_ns / num_tests
average_tokens_per_second = total_eval_count / (average_eval_duration_ns / 1e9) if average_eval_duration_ns > 0 else 0

print(f"生成 token 数: {total_eval_count}")
print(f"生成耗时: {average_eval_duration_ns / 1e9:.2f} 秒")
print(f"**Token 速度: {average_tokens_per_second:.2f} tokens/s**")
