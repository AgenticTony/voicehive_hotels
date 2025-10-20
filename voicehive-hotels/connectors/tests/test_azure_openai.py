#!/usr/bin/env python3
"""
Azure OpenAI Connection Test for VoiceHive Hotels
Test the Azure OpenAI integration for voice assistant functionality
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Add the project root to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
except ImportError:
    print("❌ python-dotenv package not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv"])
    from dotenv import load_dotenv

# Find and load the .env file
env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Loaded environment from: {env_path}")
else:
    print(f"⚠️  .env file not found at: {env_path}")
    # Try alternative path
    alt_env_path = Path("/Users/anthonyforan/voicehive-hotels/voicehive_hotels/voicehive_hotels/.env")
    if alt_env_path.exists():
        load_dotenv(alt_env_path)
        print(f"✅ Loaded environment from: {alt_env_path}")
    else:
        print(f"⚠️  .env file not found at alternative path: {alt_env_path}")

try:
    from openai import AsyncAzureOpenAI
except ImportError:
    print("❌ openai package not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openai"])
    from openai import AsyncAzureOpenAI


class AzureOpenAITester:
    """Test Azure OpenAI integration for VoiceHive"""

    def __init__(self):
        self.endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        self.api_key = os.getenv('AZURE_OPENAI_KEY')
        self.deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4')

        if not self.endpoint or not self.api_key:
            raise ValueError("Missing Azure OpenAI credentials in environment variables")

        # Remove trailing slash if present
        if self.endpoint.endswith('/'):
            self.endpoint = self.endpoint[:-1]

        self.client = AsyncAzureOpenAI(
            azure_endpoint=self.endpoint,
            api_key=self.api_key,
            api_version="2024-06-01"
        )

    async def test_basic_connection(self):
        """Test basic Azure OpenAI connection"""
        try:
            print("🔍 Testing basic Azure OpenAI connection...")

            response = await self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Say 'Hello, Azure OpenAI is working!' and nothing else."}
                ],
                max_tokens=50,
                temperature=0.1
            )

            content = response.choices[0].message.content.strip()
            print(f"✅ Connection successful!")
            print(f"✅ Response: {content}")
            return True

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    async def test_hotel_conversation(self):
        """Test hotel-specific conversation capabilities"""
        try:
            print("\n🏨 Testing hotel conversation capabilities...")

            hotel_messages = [
                {
                    "role": "system",
                    "content": """You are a hotel voice assistant for VoiceHive Hotels.
                    You help guests with reservations, questions about amenities, and general hotel information.
                    Keep responses conversational and helpful."""
                },
                {
                    "role": "user",
                    "content": "Hi, I'd like to book a room for tomorrow night. Do you have availability?"
                }
            ]

            response = await self.client.chat.completions.create(
                model=self.deployment,
                messages=hotel_messages,
                max_tokens=150,
                temperature=0.7
            )

            assistant_response = response.choices[0].message.content.strip()
            print(f"✅ Hotel conversation test successful!")
            print(f"✅ Assistant Response:")
            print(f"   {assistant_response}")

            # Test usage info
            if hasattr(response, 'usage'):
                usage = response.usage
                print(f"✅ Token usage: {usage.prompt_tokens} prompt + {usage.completion_tokens} completion = {usage.total_tokens} total")

            return True

        except Exception as e:
            print(f"❌ Hotel conversation test failed: {e}")
            return False

    async def test_multi_turn_conversation(self):
        """Test multi-turn hotel conversation"""
        try:
            print("\n💬 Testing multi-turn conversation...")

            messages = [
                {
                    "role": "system",
                    "content": "You are a hotel voice assistant. Help guests with their requests."
                },
                {
                    "role": "user",
                    "content": "What amenities do you have?"
                }
            ]

            # First exchange
            response1 = await self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                max_tokens=100,
                temperature=0.7
            )

            assistant_msg1 = response1.choices[0].message.content
            messages.append({"role": "assistant", "content": assistant_msg1})

            # Follow-up question
            messages.append({
                "role": "user",
                "content": "Great! What about the pool hours?"
            })

            response2 = await self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                max_tokens=100,
                temperature=0.7
            )

            assistant_msg2 = response2.choices[0].message.content

            print(f"✅ Multi-turn conversation successful!")
            print(f"✅ First response: {assistant_msg1[:100]}...")
            print(f"✅ Follow-up response: {assistant_msg2[:100]}...")

            return True

        except Exception as e:
            print(f"❌ Multi-turn conversation failed: {e}")
            return False

    async def test_streaming_response(self):
        """Test streaming response for real-time conversation"""
        try:
            print("\n🌊 Testing streaming response...")

            stream = await self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a hotel voice assistant."},
                    {"role": "user", "content": "Tell me about your hotel's location and nearby attractions."}
                ],
                max_tokens=150,
                temperature=0.7,
                stream=True
            )

            print("✅ Streaming response:")
            collected_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end="", flush=True)
                    collected_response += content

            print("\n✅ Streaming test successful!")
            return True

        except Exception as e:
            print(f"❌ Streaming test failed: {e}")
            return False

    async def run_comprehensive_test(self):
        """Run all Azure OpenAI tests"""
        print("🧪 VoiceHive Azure OpenAI Integration Test Suite")
        print("=" * 60)
        print(f"Endpoint: {self.endpoint}")
        print(f"Deployment: {self.deployment}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print()

        tests = [
            ("Basic Connection", self.test_basic_connection),
            ("Hotel Conversation", self.test_hotel_conversation),
            ("Multi-turn Conversation", self.test_multi_turn_conversation),
            ("Streaming Response", self.test_streaming_response)
        ]

        results = []
        for test_name, test_func in tests:
            try:
                result = await test_func()
                results.append((test_name, result))
            except Exception as e:
                print(f"❌ {test_name} test crashed: {e}")
                results.append((test_name, False))

        # Summary
        print("\n📊 TEST RESULTS SUMMARY:")
        print("=" * 40)

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")

        print(f"\nOverall: {passed}/{total} tests passed")

        if passed == total:
            print("🚀 Azure OpenAI is fully configured and ready for VoiceHive Hotels!")
            print("🎯 Your voice assistant can now process guest conversations!")
        else:
            print("⚠️  Some tests failed. Check your Azure OpenAI configuration.")

        return passed == total


async def main():
    """Run the comprehensive Azure OpenAI test"""
    try:
        tester = AzureOpenAITester()
        await tester.run_comprehensive_test()
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        print("💡 Make sure your Azure OpenAI credentials are set in the .env file")


if __name__ == "__main__":
    asyncio.run(main())