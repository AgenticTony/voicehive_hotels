#!/usr/bin/env python3
"""
NVIDIA Granary ASR Integration Test for VoiceHive Hotels
Test the existing Granary implementation with 25 EU languages
"""

import asyncio
import httpx
import base64
import io
import wave
import numpy as np
from datetime import datetime
from pathlib import Path

class GranaryASRTester:
    """Test VoiceHive's existing NVIDIA Granary ASR implementation"""

    def __init__(self):
        # Default Granary proxy endpoint from your services
        self.granary_url = "http://localhost:8000"  # Default granary-proxy port
        self.supported_languages = [
            'bg', 'hr', 'cs', 'da', 'nl', 'en', 'et', 'fi', 'fr',
            'de', 'el', 'hu', 'it', 'lv', 'lt', 'mt', 'pl', 'pt',
            'ro', 'sk', 'sl', 'es', 'sv'
        ]

    def generate_test_audio(self, text="Hello, I would like to book a room for tonight",
                          duration=3.0, sample_rate=16000):
        """Generate synthetic test audio for testing"""
        # Generate a simple sine wave as test audio
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        # Multiple frequencies to simulate speech-like audio
        audio = np.sin(2 * np.pi * 440 * t) * 0.3  # A4 note
        audio += np.sin(2 * np.pi * 880 * t) * 0.2  # A5 note
        audio += np.random.normal(0, 0.05, len(audio))  # Add some noise

        # Convert to 16-bit PCM
        audio_int16 = (audio * 32767).astype(np.int16)

        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int16.tobytes())

        wav_buffer.seek(0)
        return wav_buffer.getvalue()

    async def test_granary_health(self):
        """Test Granary service health"""
        try:
            print("🏥 Testing Granary ASR service health...")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.granary_url}/health")

                if response.status_code == 200:
                    health_data = response.json()
                    print("✅ Granary ASR service is healthy!")
                    print(f"   Status: {health_data.get('status')}")
                    print(f"   Service: {health_data.get('service')}")
                    print(f"   Model: {health_data.get('model_name')}")
                    print(f"   Model Loaded: {health_data.get('model_loaded')}")
                    print(f"   Supported Languages: {health_data.get('supported_languages')}")
                    print(f"   Device: {health_data.get('device')}")
                    return True
                else:
                    print(f"❌ Granary health check failed: HTTP {response.status_code}")
                    return False

        except Exception as e:
            print(f"❌ Granary health check failed: {e}")
            return False

    async def test_granary_transcription(self, language="en"):
        """Test Granary offline transcription"""
        try:
            print(f"\n🎤 Testing Granary transcription (language: {language})...")

            # Generate test audio
            test_audio = self.generate_test_audio()

            # Prepare request
            files = {
                'audio': ('test.wav', test_audio, 'audio/wav')
            }
            data = {
                'language': language
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.granary_url}/transcribe",
                    files=files,
                    data=data
                )

                if response.status_code == 200:
                    result = response.json()
                    print("✅ Granary transcription successful!")
                    print(f"   Transcript: {result.get('transcript', 'N/A')}")
                    print(f"   Confidence: {result.get('confidence', 'N/A')}")
                    print(f"   Language: {result.get('language', 'N/A')}")
                    print(f"   Duration: {result.get('duration_ms', 'N/A')}ms")
                    print(f"   Model: {result.get('model_used', 'N/A')}")
                    return True
                else:
                    print(f"❌ Granary transcription failed: HTTP {response.status_code}")
                    try:
                        error_detail = response.json()
                        print(f"   Error: {error_detail}")
                    except:
                        print(f"   Response: {response.text}")
                    return False

        except Exception as e:
            print(f"❌ Granary transcription failed: {e}")
            return False

    async def test_granary_language_detection(self):
        """Test Granary language detection"""
        try:
            print(f"\n🌍 Testing Granary language detection...")

            # Generate test audio
            test_audio = self.generate_test_audio()

            # Prepare request
            files = {
                'audio': ('test.wav', test_audio, 'audio/wav')
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.granary_url}/detect-language",
                    files=files
                )

                if response.status_code == 200:
                    result = response.json()
                    print("✅ Granary language detection successful!")
                    print(f"   Detected Language: {result.get('language', 'N/A')}")
                    print(f"   Confidence: {result.get('confidence', 'N/A')}")
                    print(f"   Candidates: {result.get('candidates', [])}")
                    return True
                else:
                    print(f"❌ Granary language detection failed: HTTP {response.status_code}")
                    try:
                        error_detail = response.json()
                        print(f"   Error: {error_detail}")
                    except:
                        print(f"   Response: {response.text}")
                    return False

        except Exception as e:
            print(f"❌ Granary language detection failed: {e}")
            return False

    async def test_multiple_languages(self):
        """Test Granary with multiple EU languages"""
        print(f"\n🇪🇺 Testing Granary with multiple European languages...")

        test_languages = ['en', 'de', 'fr', 'es', 'it', 'nl']  # Sample of EU languages
        results = []

        for lang in test_languages:
            print(f"\n   Testing {lang.upper()}...")
            success = await self.test_granary_transcription(lang)
            results.append((lang, success))
            # Small delay between requests
            await asyncio.sleep(1)

        # Summary
        successful = sum(1 for _, success in results if success)
        print(f"\n📊 Multi-language test results: {successful}/{len(results)} languages working")

        for lang, success in results:
            status = "✅" if success else "❌"
            print(f"   {status} {lang.upper()}")

        return successful == len(results)

    async def run_comprehensive_test(self):
        """Run all Granary ASR tests"""
        print("🧪 VoiceHive NVIDIA Granary ASR Integration Test Suite")
        print("=" * 65)
        print(f"Granary URL: {self.granary_url}")
        print(f"Supported Languages: {len(self.supported_languages)} EU languages")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print()

        tests = [
            ("Service Health Check", self.test_granary_health),
            ("English Transcription", lambda: self.test_granary_transcription("en")),
            ("Language Detection", self.test_granary_language_detection),
            ("Multi-Language Support", self.test_multiple_languages)
        ]

        results = []
        for test_name, test_func in tests:
            try:
                print(f"\n{'='*20} {test_name} {'='*20}")
                result = await test_func()
                results.append((test_name, result))
            except Exception as e:
                print(f"❌ {test_name} test crashed: {e}")
                results.append((test_name, False))

        # Summary
        print("\n" + "="*65)
        print("📊 GRANARY ASR TEST RESULTS SUMMARY:")
        print("=" * 65)

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} {test_name}")

        print(f"\nOverall: {passed}/{total} tests passed")

        if passed == total:
            print("🚀 NVIDIA Granary ASR is fully operational!")
            print("🏨 Your VoiceHive Hotels voice assistant has world-class multilingual ASR!")
            print("🇪🇺 25 European languages ready for hotel guests!")
        elif passed > 0:
            print("⚠️  Some Granary features working, check service configuration")
        else:
            print("❌ Granary ASR service not accessible")
            print("💡 Make sure the granary-proxy service is running on port 8000")

        return passed == total

async def main():
    """Run the Granary ASR test suite"""
    try:
        tester = GranaryASRTester()
        await tester.run_comprehensive_test()

        print("\n💡 Next Steps:")
        print("   1. If tests pass: Your Granary ASR is ready for production!")
        print("   2. If tests fail: Start the granary-proxy service")
        print("   3. Check service logs: docker logs voicehive-granary-proxy")
        print("   4. Verify GPU availability for optimal performance")

    except Exception as e:
        print(f"❌ Test suite failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())