from dotenv import load_dotenv
import anthropic

load_dotenv()  # reads backend/.env into environment variables
client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY automatically

response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=1024,
    output_config={"effort": "low"},  # simple question -> don't think hard
    messages=[{"role": "user", "content": "In one sentence: what is a health insurance deductible?"}],
)

for block in response.content:
    if block.type == "text":
        print(block.text)

print("---")
print("tokens in:", response.usage.input_tokens, "| tokens out:", response.usage.output_tokens)
