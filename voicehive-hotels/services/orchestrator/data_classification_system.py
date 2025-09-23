"""
Data Classification System for VoiceHive Hotels
Automated PII detection, data classification, and sensitivity labeling with ML-based analysis
"""

import asyncio
import json
import re
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple, Union
from enum import Enum
from dataclasses import dataclass, asdict, field
from pathlib import Path
import uuid

from pydantic import BaseModel, Field, validator
import spacy
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity
from enhanced_pii_redactor import PIICategory, RedactionLevel

logger = get_safe_logger("orchestrator.data_classification")


class DataSensitivityLevel(str, Enum):
    """Data sensitivity classification levels"""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    TOP_SECRET = "top_secret"


class DataClassification(str, Enum):
    """Data classification categories"""
    PERSONAL_DATA = "personal_data"
    SENSITIVE_PERSONAL_DATA = "sensitive_personal_data"
    FINANCIAL_DATA = "financial_data"
    HEALTH_DATA = "health_data"
    BIOMETRIC_DATA = "biometric_data"
    BUSINESS_DATA = "business_data"
    TECHNICAL_DATA = "technical_data"
    PUBLIC_DATA = "public_data"


class PIIType(str, Enum):
    """Specific types of PII detected"""
    # Identity
    FULL_NAME = "full_name"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    USERNAME = "username"
    
    # Contact Information
    EMAIL_ADDRESS = "email_address"
    PHONE_NUMBER = "phone_number"
    ADDRESS = "address"
    POSTAL_CODE = "postal_code"
    
    # Identification Numbers
    SSN = "ssn"
    PASSPORT_NUMBER = "passport_number"
    DRIVER_LICENSE = "driver_license"
    ID_NUMBER = "id_number"
    
    # Financial
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    IBAN = "iban"
    
    # Technical
    IP_ADDRESS = "ip_address"
    MAC_ADDRESS = "mac_address"
    URL = "url"
    
    # Hotel Specific
    ROOM_NUMBER = "room_number"
    CONFIRMATION_CODE = "confirmation_code"
    GUEST_ID = "guest_id"
    
    # Biometric
    VOICE_PRINT = "voice_print"
    FACIAL_FEATURES = "facial_features"
    
    # Location
    GPS_COORDINATES = "gps_coordinates"
    GEOLOCATION = "geolocation"


@dataclass
class PIIDetection:
    """Result of PII detection analysis"""
    pii_type: PIIType
    value: str
    confidence: float
    start_position: int
    end_position: int
    context: str
    detection_method: str  # regex, ml, rule_based
    
    # Classification
    sensitivity_level: DataSensitivityLevel
    data_classification: DataClassification
    
    # Recommendations
    recommended_action: RedactionLevel
    retention_period: Optional[int] = None  # days
    
    # Metadata
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detector_version: str = "1.0"


@dataclass
class DataClassificationResult:
    """Complete data classification analysis result"""
    content_id: str
    content_type: str  # text, audio, image, document
    analyzed_at: datetime
    
    # Overall classification
    overall_sensitivity: DataSensitivityLevel
    overall_classification: DataClassification
    
    # PII detections
    pii_detections: List[PIIDetection]
    pii_count: int
    
    # Statistics
    confidence_score: float
    processing_time_ms: int
    
    # Recommendations
    recommended_retention_days: int
    recommended_access_controls: List[str]
    compliance_requirements: List[str]
    
    # Metadata
    analyzer_version: str = "1.0"
    model_versions: Dict[str, str] = field(default_factory=dict)


class DataClassificationEngine:
    """Advanced data classification and PII detection engine"""
    
    def __init__(self, 
                 audit_logger: Optional[AuditLogger] = None,
                 config_path: Optional[str] = None):
        self.audit_logger = audit_logger or AuditLogger()
        self.config = self._load_config(config_path)
        
        # Initialize NLP models
        self.nlp_engine = None
        self.presidio_analyzer = None
        self.presidio_anonymizer = None
        
        # Classification rules
        self.classification_rules = self._load_classification_rules()
        self.sensitivity_mappings = self._load_sensitivity_mappings()
        
        # Statistics
        self.analysis_stats = {
            "total_analyses": 0,
            "pii_detections": 0,
            "by_sensitivity": {},
            "by_classification": {},
            "by_pii_type": {}
        }
        
        # Initialize engines
        asyncio.create_task(self._initialize_engines())
    
    async def _initialize_engines(self):
        """Initialize ML and NLP engines"""
        try:
            # Initialize Presidio analyzer
            nlp_configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]
            }
            
            nlp_engine_provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
            nlp_engine = nlp_engine_provider.create_engine()
            
            self.presidio_analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
            self.presidio_anonymizer = AnonymizerEngine()
            
            # Load spaCy model
            try:
                self.nlp_engine = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning("spaCy model 'en_core_web_sm' not found. Some features may be limited.")
                self.nlp_engine = None
            
            logger.info("Data classification engines initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize classification engines: {e}")
            # Continue with limited functionality
    
    async def classify_text(self, 
                          text: str, 
                          content_id: Optional[str] = None,
                          context: Optional[str] = None) -> DataClassificationResult:
        """Classify text content and detect PII"""
        
        start_time = datetime.now(timezone.utc)
        content_id = content_id or str(uuid.uuid4())
        
        # Initialize result
        result = DataClassificationResult(
            content_id=content_id,
            content_type="text",
            analyzed_at=start_time,
            overall_sensitivity=DataSensitivityLevel.PUBLIC,
            overall_classification=DataClassification.PUBLIC_DATA,
            pii_detections=[],
            pii_count=0,
            confidence_score=0.0,
            processing_time_ms=0,
            recommended_retention_days=365,
            recommended_access_controls=[],
            compliance_requirements=[]
        )
        
        try:
            # Detect PII using multiple methods
            pii_detections = []
            
            # Method 1: Presidio-based detection
            if self.presidio_analyzer:
                presidio_results = await self._detect_pii_presidio(text, context)
                pii_detections.extend(presidio_results)
            
            # Method 2: Regex-based detection
            regex_results = await self._detect_pii_regex(text, context)
            pii_detections.extend(regex_results)
            
            # Method 3: NLP-based detection
            if self.nlp_engine:
                nlp_results = await self._detect_pii_nlp(text, context)
                pii_detections.extend(nlp_results)
            
            # Method 4: Hotel-specific detection
            hotel_results = await self._detect_hotel_specific_pii(text, context)
            pii_detections.extend(hotel_results)
            
            # Deduplicate and merge overlapping detections
            pii_detections = self._deduplicate_detections(pii_detections)
            
            # Classify overall content
            overall_classification = self._classify_content(pii_detections, text, context)
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(pii_detections)
            
            # Generate recommendations
            recommendations = self._generate_recommendations(pii_detections, overall_classification)
            
            # Update result
            result.pii_detections = pii_detections
            result.pii_count = len(pii_detections)
            result.overall_sensitivity = overall_classification["sensitivity"]
            result.overall_classification = overall_classification["classification"]
            result.confidence_score = confidence_score
            result.recommended_retention_days = recommendations["retention_days"]
            result.recommended_access_controls = recommendations["access_controls"]
            result.compliance_requirements = recommendations["compliance_requirements"]
            
            # Calculate processing time
            end_time = datetime.now(timezone.utc)
            result.processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
            
            # Update statistics
            self._update_statistics(result)
            
            # Audit the classification
            self.audit_logger.log_event(
                event_type=AuditEventType.PII_ACCESS,
                description=f"Data classification completed: {len(pii_detections)} PII items detected",
                severity=AuditSeverity.MEDIUM,
                resource_type="data_classification",
                resource_id=content_id,
                action="classify",
                metadata={
                    "pii_count": len(pii_detections),
                    "sensitivity_level": result.overall_sensitivity.value,
                    "classification": result.overall_classification.value,
                    "confidence_score": confidence_score
                },
                retention_period=365
            )
            
            logger.info(f"Text classification completed: {content_id} - {len(pii_detections)} PII items detected")
            
        except Exception as e:
            logger.error(f"Text classification failed for {content_id}: {e}")
            result.confidence_score = 0.0
            result.processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        return result
    
    async def classify_structured_data(self, 
                                     data: Dict[str, Any], 
                                     content_id: Optional[str] = None,
                                     schema_info: Optional[Dict[str, Any]] = None) -> DataClassificationResult:
        """Classify structured data (JSON, database records, etc.)"""
        
        start_time = datetime.now(timezone.utc)
        content_id = content_id or str(uuid.uuid4())
        
        # Convert structured data to text for analysis
        text_content = self._structured_data_to_text(data)
        
        # Perform text classification
        result = await self.classify_text(text_content, content_id, "structured_data")
        result.content_type = "structured_data"
        
        # Additional structured data analysis
        field_classifications = await self._classify_data_fields(data, schema_info)
        
        # Merge field-level classifications
        for field_name, field_classification in field_classifications.items():
            if field_classification["has_pii"]:
                # Add field-specific PII detection
                pii_detection = PIIDetection(
                    pii_type=field_classification["pii_type"],
                    value=str(data.get(field_name, "")),
                    confidence=field_classification["confidence"],
                    start_position=0,
                    end_position=len(str(data.get(field_name, ""))),
                    context=f"field:{field_name}",
                    detection_method="field_analysis",
                    sensitivity_level=field_classification["sensitivity"],
                    data_classification=field_classification["classification"],
                    recommended_action=field_classification["recommended_action"]
                )
                result.pii_detections.append(pii_detection)
        
        # Recalculate overall classification
        overall_classification = self._classify_content(result.pii_detections, text_content, "structured_data")
        result.overall_sensitivity = overall_classification["sensitivity"]
        result.overall_classification = overall_classification["classification"]
        result.pii_count = len(result.pii_detections)
        
        logger.info(f"Structured data classification completed: {content_id}")
        return result
    
    async def classify_audio_metadata(self, 
                                    metadata: Dict[str, Any], 
                                    transcript: Optional[str] = None,
                                    content_id: Optional[str] = None) -> DataClassificationResult:
        """Classify audio content based on metadata and transcript"""
        
        content_id = content_id or str(uuid.uuid4())
        
        # Combine metadata and transcript for analysis
        combined_text = ""
        if transcript:
            combined_text += f"Transcript: {transcript}\n"
        
        # Add relevant metadata as text
        for key, value in metadata.items():
            if key in ["caller_id", "guest_name", "room_number", "phone_number"]:
                combined_text += f"{key}: {value}\n"
        
        # Perform classification
        result = await self.classify_text(combined_text, content_id, "audio")
        result.content_type = "audio"
        
        # Audio-specific classifications
        if "voice_print" in metadata:
            voice_detection = PIIDetection(
                pii_type=PIIType.VOICE_PRINT,
                value="[VOICE_BIOMETRIC_DATA]",
                confidence=1.0,
                start_position=0,
                end_position=0,
                context="audio_metadata",
                detection_method="metadata_analysis",
                sensitivity_level=DataSensitivityLevel.RESTRICTED,
                data_classification=DataClassification.BIOMETRIC_DATA,
                recommended_action=RedactionLevel.FULL
            )
            result.pii_detections.append(voice_detection)
        
        # Update classification based on audio-specific PII
        if result.pii_detections:
            overall_classification = self._classify_content(result.pii_detections, combined_text, "audio")
            result.overall_sensitivity = overall_classification["sensitivity"]
            result.overall_classification = overall_classification["classification"]
        
        logger.info(f"Audio metadata classification completed: {content_id}")
        return result
    
    async def _detect_pii_presidio(self, text: str, context: Optional[str] = None) -> List[PIIDetection]:
        """Detect PII using Presidio analyzer"""
        
        detections = []
        
        if not self.presidio_analyzer:
            return detections
        
        try:
            # Analyze text with Presidio
            analyzer_results = self.presidio_analyzer.analyze(
                text=text,
                language="en",
                entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", 
                         "IBAN_CODE", "IP_ADDRESS", "US_SSN", "US_PASSPORT"]
            )
            
            # Convert Presidio results to our format
            for result in analyzer_results:
                pii_type = self._map_presidio_entity_type(result.entity_type)
                if pii_type:
                    detection = PIIDetection(
                        pii_type=pii_type,
                        value=text[result.start:result.end],
                        confidence=result.score,
                        start_position=result.start,
                        end_position=result.end,
                        context=context or "text",
                        detection_method="presidio_ml",
                        sensitivity_level=self._get_sensitivity_for_pii_type(pii_type),
                        data_classification=self._get_classification_for_pii_type(pii_type),
                        recommended_action=self._get_recommended_action_for_pii_type(pii_type)
                    )
                    detections.append(detection)
        
        except Exception as e:
            logger.error(f"Presidio PII detection failed: {e}")
        
        return detections
    
    async def _detect_pii_regex(self, text: str, context: Optional[str] = None) -> List[PIIDetection]:
        """Detect PII using regex patterns"""
        
        detections = []
        
        # Define regex patterns for various PII types
        patterns = {
            PIIType.EMAIL_ADDRESS: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            PIIType.PHONE_NUMBER: r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b',
            PIIType.CREDIT_CARD: r'\b(?:\d[ -]*?){13,19}\b',
            PIIType.SSN: r'\b\d{3}-\d{2}-\d{4}\b',
            PIIType.IP_ADDRESS: r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
            PIIType.POSTAL_CODE: r'\b\d{5}(?:-\d{4})?\b',
            PIIType.ROOM_NUMBER: r'\b(?:room|suite|rm)\s*#?\s*(\d{1,4}[A-Za-z]?)\b',
            PIIType.CONFIRMATION_CODE: r'\b(?:confirmation|conf|booking|res)\s*#?\s*([A-Z0-9]{6,12})\b'
        }
        
        for pii_type, pattern in patterns.items():
            try:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    detection = PIIDetection(
                        pii_type=pii_type,
                        value=match.group(),
                        confidence=0.9,  # High confidence for regex matches
                        start_position=match.start(),
                        end_position=match.end(),
                        context=context or "text",
                        detection_method="regex",
                        sensitivity_level=self._get_sensitivity_for_pii_type(pii_type),
                        data_classification=self._get_classification_for_pii_type(pii_type),
                        recommended_action=self._get_recommended_action_for_pii_type(pii_type)
                    )
                    detections.append(detection)
            
            except Exception as e:
                logger.error(f"Regex detection failed for {pii_type}: {e}")
        
        return detections
    
    async def _detect_pii_nlp(self, text: str, context: Optional[str] = None) -> List[PIIDetection]:
        """Detect PII using NLP models"""
        
        detections = []
        
        if not self.nlp_engine:
            return detections
        
        try:
            # Process text with spaCy
            doc = self.nlp_engine(text)
            
            # Extract named entities
            for ent in doc.ents:
                pii_type = self._map_spacy_entity_type(ent.label_)
                if pii_type:
                    detection = PIIDetection(
                        pii_type=pii_type,
                        value=ent.text,
                        confidence=0.8,  # Medium confidence for NLP
                        start_position=ent.start_char,
                        end_position=ent.end_char,
                        context=context or "text",
                        detection_method="spacy_nlp",
                        sensitivity_level=self._get_sensitivity_for_pii_type(pii_type),
                        data_classification=self._get_classification_for_pii_type(pii_type),
                        recommended_action=self._get_recommended_action_for_pii_type(pii_type)
                    )
                    detections.append(detection)
        
        except Exception as e:
            logger.error(f"NLP PII detection failed: {e}")
        
        return detections
    
    async def _detect_hotel_specific_pii(self, text: str, context: Optional[str] = None) -> List[PIIDetection]:
        """Detect hotel-specific PII patterns"""
        
        detections = []
        
        # Hotel-specific patterns
        hotel_patterns = {
            PIIType.ROOM_NUMBER: [
                r'\b(?:room|suite|rm|unit)\s*#?\s*(\d{1,4}[A-Za-z]?)\b',
                r'\b(\d{3,4}[A-Za-z]?)\s*(?:room|suite)\b'
            ],
            PIIType.CONFIRMATION_CODE: [
                r'\b(?:confirmation|conf|booking|res|reservation)\s*#?\s*([A-Z0-9]{6,12})\b',
                r'\b([A-Z]{2}\d{6,8})\b'  # Common hotel confirmation format
            ],
            PIIType.GUEST_ID: [
                r'\b(?:guest|customer)\s*#?\s*([A-Z0-9]{6,12})\b',
                r'\bGST[0-9]{6,8}\b'
            ]
        }
        
        for pii_type, patterns in hotel_patterns.items():
            for pattern in patterns:
                try:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        detection = PIIDetection(
                            pii_type=pii_type,
                            value=match.group(),
                            confidence=0.85,
                            start_position=match.start(),
                            end_position=match.end(),
                            context=context or "hotel_specific",
                            detection_method="hotel_regex",
                            sensitivity_level=self._get_sensitivity_for_pii_type(pii_type),
                            data_classification=self._get_classification_for_pii_type(pii_type),
                            recommended_action=self._get_recommended_action_for_pii_type(pii_type)
                        )
                        detections.append(detection)
                
                except Exception as e:
                    logger.error(f"Hotel-specific detection failed for {pii_type}: {e}")
        
        return detections
    
    async def _classify_data_fields(self, 
                                  data: Dict[str, Any], 
                                  schema_info: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """Classify individual data fields"""
        
        field_classifications = {}
        
        # Field name to PII type mappings
        field_mappings = {
            "email": PIIType.EMAIL_ADDRESS,
            "phone": PIIType.PHONE_NUMBER,
            "phone_number": PIIType.PHONE_NUMBER,
            "first_name": PIIType.FIRST_NAME,
            "last_name": PIIType.LAST_NAME,
            "full_name": PIIType.FULL_NAME,
            "name": PIIType.FULL_NAME,
            "address": PIIType.ADDRESS,
            "ssn": PIIType.SSN,
            "credit_card": PIIType.CREDIT_CARD,
            "room_number": PIIType.ROOM_NUMBER,
            "confirmation_code": PIIType.CONFIRMATION_CODE,
            "ip_address": PIIType.IP_ADDRESS
        }
        
        for field_name, field_value in data.items():
            field_name_lower = field_name.lower()
            
            # Check if field name indicates PII
            pii_type = None
            for key, mapped_type in field_mappings.items():
                if key in field_name_lower:
                    pii_type = mapped_type
                    break
            
            # Analyze field value if no direct mapping
            if not pii_type and isinstance(field_value, str):
                # Use regex to detect PII in field value
                value_detections = await self._detect_pii_regex(field_value)
                if value_detections:
                    pii_type = value_detections[0].pii_type
            
            # Classify field
            if pii_type:
                field_classifications[field_name] = {
                    "has_pii": True,
                    "pii_type": pii_type,
                    "confidence": 0.9,
                    "sensitivity": self._get_sensitivity_for_pii_type(pii_type),
                    "classification": self._get_classification_for_pii_type(pii_type),
                    "recommended_action": self._get_recommended_action_for_pii_type(pii_type)
                }
            else:
                field_classifications[field_name] = {
                    "has_pii": False,
                    "pii_type": None,
                    "confidence": 0.0,
                    "sensitivity": DataSensitivityLevel.INTERNAL,
                    "classification": DataClassification.BUSINESS_DATA,
                    "recommended_action": RedactionLevel.NONE
                }
        
        return field_classifications
    
    def _deduplicate_detections(self, detections: List[PIIDetection]) -> List[PIIDetection]:
        """Remove duplicate and overlapping PII detections"""
        
        if not detections:
            return detections
        
        # Sort by start position
        sorted_detections = sorted(detections, key=lambda x: x.start_position)
        
        deduplicated = []
        for detection in sorted_detections:
            # Check for overlaps with existing detections
            overlaps = False
            for existing in deduplicated:
                if (detection.start_position < existing.end_position and 
                    detection.end_position > existing.start_position):
                    # Overlapping detection - keep the one with higher confidence
                    if detection.confidence > existing.confidence:
                        deduplicated.remove(existing)
                        deduplicated.append(detection)
                    overlaps = True
                    break
            
            if not overlaps:
                deduplicated.append(detection)
        
        return deduplicated
    
    def _classify_content(self, 
                         pii_detections: List[PIIDetection], 
                         text: str, 
                         context: Optional[str] = None) -> Dict[str, Any]:
        """Classify overall content based on PII detections"""
        
        if not pii_detections:
            return {
                "sensitivity": DataSensitivityLevel.PUBLIC,
                "classification": DataClassification.PUBLIC_DATA
            }
        
        # Determine highest sensitivity level
        max_sensitivity = DataSensitivityLevel.PUBLIC
        classifications = set()
        
        for detection in pii_detections:
            # Update max sensitivity
            sensitivity_levels = [
                DataSensitivityLevel.PUBLIC,
                DataSensitivityLevel.INTERNAL,
                DataSensitivityLevel.CONFIDENTIAL,
                DataSensitivityLevel.RESTRICTED,
                DataSensitivityLevel.TOP_SECRET
            ]
            
            if sensitivity_levels.index(detection.sensitivity_level) > sensitivity_levels.index(max_sensitivity):
                max_sensitivity = detection.sensitivity_level
            
            classifications.add(detection.data_classification)
        
        # Determine overall classification
        classification_priority = [
            DataClassification.BIOMETRIC_DATA,
            DataClassification.HEALTH_DATA,
            DataClassification.SENSITIVE_PERSONAL_DATA,
            DataClassification.FINANCIAL_DATA,
            DataClassification.PERSONAL_DATA,
            DataClassification.BUSINESS_DATA,
            DataClassification.TECHNICAL_DATA,
            DataClassification.PUBLIC_DATA
        ]
        
        overall_classification = DataClassification.PUBLIC_DATA
        for classification in classification_priority:
            if classification in classifications:
                overall_classification = classification
                break
        
        return {
            "sensitivity": max_sensitivity,
            "classification": overall_classification
        }
    
    def _calculate_confidence_score(self, pii_detections: List[PIIDetection]) -> float:
        """Calculate overall confidence score for classification"""
        
        if not pii_detections:
            return 1.0  # High confidence for no PII
        
        # Average confidence of all detections
        total_confidence = sum(detection.confidence for detection in pii_detections)
        return total_confidence / len(pii_detections)
    
    def _generate_recommendations(self, 
                                pii_detections: List[PIIDetection], 
                                overall_classification: Dict[str, Any]) -> Dict[str, Any]:
        """Generate recommendations based on classification"""
        
        recommendations = {
            "retention_days": 365,
            "access_controls": ["authenticated_users"],
            "compliance_requirements": []
        }
        
        # Determine retention period based on classification
        classification = overall_classification["classification"]
        sensitivity = overall_classification["sensitivity"]
        
        retention_mappings = {
            DataClassification.BIOMETRIC_DATA: 30,
            DataClassification.HEALTH_DATA: 2555,  # 7 years
            DataClassification.FINANCIAL_DATA: 2555,
            DataClassification.SENSITIVE_PERSONAL_DATA: 365,
            DataClassification.PERSONAL_DATA: 365,
            DataClassification.BUSINESS_DATA: 1095,  # 3 years
            DataClassification.TECHNICAL_DATA: 730,  # 2 years
            DataClassification.PUBLIC_DATA: 365
        }
        
        recommendations["retention_days"] = retention_mappings.get(classification, 365)
        
        # Access controls based on sensitivity
        if sensitivity in [DataSensitivityLevel.RESTRICTED, DataSensitivityLevel.TOP_SECRET]:
            recommendations["access_controls"] = ["admin_only", "mfa_required", "audit_all_access"]
        elif sensitivity == DataSensitivityLevel.CONFIDENTIAL:
            recommendations["access_controls"] = ["authorized_users", "audit_access"]
        elif sensitivity == DataSensitivityLevel.INTERNAL:
            recommendations["access_controls"] = ["authenticated_users"]
        
        # Compliance requirements
        pii_types = {detection.pii_type for detection in pii_detections}
        
        if any(pii_type in [PIIType.SSN, PIIType.CREDIT_CARD, PIIType.BANK_ACCOUNT] for pii_type in pii_types):
            recommendations["compliance_requirements"].extend(["PCI-DSS", "SOX"])
        
        if any(pii_type in [PIIType.EMAIL_ADDRESS, PIIType.FULL_NAME, PIIType.PHONE_NUMBER] for pii_type in pii_types):
            recommendations["compliance_requirements"].extend(["GDPR", "CCPA"])
        
        if classification == DataClassification.HEALTH_DATA:
            recommendations["compliance_requirements"].append("HIPAA")
        
        if classification == DataClassification.BIOMETRIC_DATA:
            recommendations["compliance_requirements"].extend(["GDPR", "BIPA"])
        
        return recommendations
    
    def _structured_data_to_text(self, data: Dict[str, Any]) -> str:
        """Convert structured data to text for analysis"""
        
        text_parts = []
        
        def extract_text(obj, prefix=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    extract_text(value, f"{prefix}.{key}" if prefix else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    extract_text(item, f"{prefix}[{i}]")
            else:
                text_parts.append(f"{prefix}: {str(obj)}")
        
        extract_text(data)
        return "\n".join(text_parts)
    
    def _update_statistics(self, result: DataClassificationResult):
        """Update analysis statistics"""
        
        self.analysis_stats["total_analyses"] += 1
        self.analysis_stats["pii_detections"] += result.pii_count
        
        # Update by sensitivity
        sensitivity = result.overall_sensitivity.value
        self.analysis_stats["by_sensitivity"][sensitivity] = self.analysis_stats["by_sensitivity"].get(sensitivity, 0) + 1
        
        # Update by classification
        classification = result.overall_classification.value
        self.analysis_stats["by_classification"][classification] = self.analysis_stats["by_classification"].get(classification, 0) + 1
        
        # Update by PII type
        for detection in result.pii_detections:
            pii_type = detection.pii_type.value
            self.analysis_stats["by_pii_type"][pii_type] = self.analysis_stats["by_pii_type"].get(pii_type, 0) + 1
    
    def get_classification_statistics(self) -> Dict[str, Any]:
        """Get comprehensive classification statistics"""
        
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "statistics": self.analysis_stats.copy(),
            "engine_status": {
                "presidio_available": self.presidio_analyzer is not None,
                "spacy_available": self.nlp_engine is not None,
                "total_pii_types": len(PIIType),
                "total_classifications": len(DataClassification),
                "total_sensitivity_levels": len(DataSensitivityLevel)
            }
        }
    
    # Helper methods for mapping and configuration
    
    def _map_presidio_entity_type(self, entity_type: str) -> Optional[PIIType]:
        """Map Presidio entity types to our PII types"""
        
        mappings = {
            "PERSON": PIIType.FULL_NAME,
            "EMAIL_ADDRESS": PIIType.EMAIL_ADDRESS,
            "PHONE_NUMBER": PIIType.PHONE_NUMBER,
            "CREDIT_CARD": PIIType.CREDIT_CARD,
            "IBAN_CODE": PIIType.IBAN,
            "IP_ADDRESS": PIIType.IP_ADDRESS,
            "US_SSN": PIIType.SSN,
            "US_PASSPORT": PIIType.PASSPORT_NUMBER
        }
        
        return mappings.get(entity_type)
    
    def _map_spacy_entity_type(self, entity_label: str) -> Optional[PIIType]:
        """Map spaCy entity labels to our PII types"""
        
        mappings = {
            "PERSON": PIIType.FULL_NAME,
            "GPE": PIIType.ADDRESS,  # Geopolitical entity
            "ORG": None,  # Organization - not PII
            "MONEY": None,  # Money - not necessarily PII
            "DATE": None,  # Date - not PII by itself
            "TIME": None,  # Time - not PII by itself
        }
        
        return mappings.get(entity_label)
    
    def _get_sensitivity_for_pii_type(self, pii_type: PIIType) -> DataSensitivityLevel:
        """Get sensitivity level for PII type"""
        
        sensitivity_mappings = {
            # High sensitivity
            PIIType.SSN: DataSensitivityLevel.RESTRICTED,
            PIIType.PASSPORT_NUMBER: DataSensitivityLevel.RESTRICTED,
            PIIType.CREDIT_CARD: DataSensitivityLevel.RESTRICTED,
            PIIType.BANK_ACCOUNT: DataSensitivityLevel.RESTRICTED,
            PIIType.VOICE_PRINT: DataSensitivityLevel.RESTRICTED,
            PIIType.FACIAL_FEATURES: DataSensitivityLevel.RESTRICTED,
            
            # Medium sensitivity
            PIIType.FULL_NAME: DataSensitivityLevel.CONFIDENTIAL,
            PIIType.EMAIL_ADDRESS: DataSensitivityLevel.CONFIDENTIAL,
            PIIType.PHONE_NUMBER: DataSensitivityLevel.CONFIDENTIAL,
            PIIType.ADDRESS: DataSensitivityLevel.CONFIDENTIAL,
            PIIType.DRIVER_LICENSE: DataSensitivityLevel.CONFIDENTIAL,
            
            # Lower sensitivity
            PIIType.FIRST_NAME: DataSensitivityLevel.INTERNAL,
            PIIType.LAST_NAME: DataSensitivityLevel.INTERNAL,
            PIIType.ROOM_NUMBER: DataSensitivityLevel.INTERNAL,
            PIIType.CONFIRMATION_CODE: DataSensitivityLevel.INTERNAL,
            PIIType.IP_ADDRESS: DataSensitivityLevel.INTERNAL,
        }
        
        return sensitivity_mappings.get(pii_type, DataSensitivityLevel.INTERNAL)
    
    def _get_classification_for_pii_type(self, pii_type: PIIType) -> DataClassification:
        """Get data classification for PII type"""
        
        classification_mappings = {
            PIIType.VOICE_PRINT: DataClassification.BIOMETRIC_DATA,
            PIIType.FACIAL_FEATURES: DataClassification.BIOMETRIC_DATA,
            
            PIIType.CREDIT_CARD: DataClassification.FINANCIAL_DATA,
            PIIType.BANK_ACCOUNT: DataClassification.FINANCIAL_DATA,
            PIIType.IBAN: DataClassification.FINANCIAL_DATA,
            
            PIIType.SSN: DataClassification.SENSITIVE_PERSONAL_DATA,
            PIIType.PASSPORT_NUMBER: DataClassification.SENSITIVE_PERSONAL_DATA,
            PIIType.DRIVER_LICENSE: DataClassification.SENSITIVE_PERSONAL_DATA,
            
            PIIType.IP_ADDRESS: DataClassification.TECHNICAL_DATA,
            PIIType.MAC_ADDRESS: DataClassification.TECHNICAL_DATA,
            PIIType.URL: DataClassification.TECHNICAL_DATA,
        }
        
        return classification_mappings.get(pii_type, DataClassification.PERSONAL_DATA)
    
    def _get_recommended_action_for_pii_type(self, pii_type: PIIType) -> RedactionLevel:
        """Get recommended redaction action for PII type"""
        
        action_mappings = {
            # Full redaction for highly sensitive data
            PIIType.SSN: RedactionLevel.FULL,
            PIIType.PASSPORT_NUMBER: RedactionLevel.FULL,
            PIIType.CREDIT_CARD: RedactionLevel.FULL,
            PIIType.BANK_ACCOUNT: RedactionLevel.FULL,
            PIIType.VOICE_PRINT: RedactionLevel.FULL,
            PIIType.FACIAL_FEATURES: RedactionLevel.FULL,
            
            # Partial redaction for moderately sensitive data
            PIIType.EMAIL_ADDRESS: RedactionLevel.PARTIAL,
            PIIType.PHONE_NUMBER: RedactionLevel.PARTIAL,
            PIIType.FULL_NAME: RedactionLevel.PARTIAL,
            PIIType.ADDRESS: RedactionLevel.PARTIAL,
            
            # Hash for technical data
            PIIType.IP_ADDRESS: RedactionLevel.HASH,
            PIIType.MAC_ADDRESS: RedactionLevel.HASH,
            
            # Partial for hotel-specific data
            PIIType.ROOM_NUMBER: RedactionLevel.PARTIAL,
            PIIType.CONFIRMATION_CODE: RedactionLevel.PARTIAL,
        }
        
        return action_mappings.get(pii_type, RedactionLevel.PARTIAL)
    
    def _load_classification_rules(self) -> Dict[str, Any]:
        """Load classification rules configuration"""
        
        return {
            "confidence_thresholds": {
                "high": 0.9,
                "medium": 0.7,
                "low": 0.5
            },
            "context_weights": {
                "audio": 1.2,
                "structured_data": 1.1,
                "text": 1.0
            }
        }
    
    def _load_sensitivity_mappings(self) -> Dict[str, Any]:
        """Load sensitivity level mappings"""
        
        return {
            "default_retention_days": {
                DataSensitivityLevel.PUBLIC: 365,
                DataSensitivityLevel.INTERNAL: 730,
                DataSensitivityLevel.CONFIDENTIAL: 1095,
                DataSensitivityLevel.RESTRICTED: 2555,
                DataSensitivityLevel.TOP_SECRET: 2555
            }
        }
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load classification configuration"""
        
        default_config = {
            "enable_presidio": True,
            "enable_spacy": True,
            "enable_regex": True,
            "confidence_threshold": 0.7,
            "max_text_length": 1000000,
            "batch_size": 1000
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load classification config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_data_classification():
        # Create classification engine
        engine = DataClassificationEngine()
        
        # Wait for initialization
        await asyncio.sleep(1)
        
        # Test text classification
        test_text = """
        Hello, this is John Doe calling from room 425. 
        My email is john.doe@example.com and my phone number is +1-555-123-4567.
        My confirmation code is ABC123XYZ and my credit card ending in 1234 was charged.
        """
        
        result = await engine.classify_text(test_text, "test_001")
        print(f"Text classification: {result.pii_count} PII items detected")
        print(f"Sensitivity: {result.overall_sensitivity.value}")
        print(f"Classification: {result.overall_classification.value}")
        
        # Test structured data classification
        test_data = {
            "guest_name": "Jane Smith",
            "email": "jane.smith@hotel.com",
            "room_number": "Suite 1012",
            "phone": "+1-555-987-6543",
            "credit_card": "4111-1111-1111-1111",
            "check_in_date": "2024-01-15"
        }
        
        structured_result = await engine.classify_structured_data(test_data, "test_002")
        print(f"Structured data classification: {structured_result.pii_count} PII items detected")
        
        # Test statistics
        stats = engine.get_classification_statistics()
        print(f"Total analyses: {stats['statistics']['total_analyses']}")
        
        print("Data classification test completed successfully")
    
    # Run test
    asyncio.run(test_data_classification())