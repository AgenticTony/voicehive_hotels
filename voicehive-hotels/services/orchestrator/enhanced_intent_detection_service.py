"""
Enhanced Intent Detection Service for Sprint 3
Supports multi-intent detection, advanced confidence scoring, and conversation context
"""

import re
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from .logging_adapter import get_safe_logger
from .models import (
    IntentType,
    DetectedIntent,
    MultiIntentDetectionResult,
    ConfidenceLevel,
    ConversationSlot
)

logger = get_safe_logger("orchestrator.enhanced_intent_detection")


class EnhancedIntentDetectionService:
    """Enhanced intent detection service with multi-intent support"""

    def __init__(self):
        self.stats = defaultdict(int)
        self.confidence_stats = defaultdict(int)
        self.language_stats = defaultdict(int)

        # Enhanced multilingual patterns for Sprint 3
        self._initialize_enhanced_patterns()

        # Intent priority for disambiguation
        self.intent_priorities = {
            IntentType.END_CALL: 10,
            IntentType.TRANSFER_TO_OPERATOR: 9,
            IntentType.FALLBACK_TO_HUMAN: 9,
            IntentType.COMPLAINT_FEEDBACK: 8,
            IntentType.EXISTING_RESERVATION_CANCEL: 7,
            IntentType.EXISTING_RESERVATION_MODIFY: 6,
            IntentType.BOOKING_INQUIRY: 5,
            IntentType.UPSELLING_OPPORTUNITY: 4,
            IntentType.RESTAURANT_BOOKING: 3,
            IntentType.SPA_BOOKING: 3,
            IntentType.ROOM_SERVICE: 3,
            IntentType.CONCIERGE_SERVICES: 2,
            IntentType.REQUEST_INFO: 1,
            IntentType.QUESTION: 1,
            IntentType.GREETING: 0,
        }

    def _initialize_enhanced_patterns(self):
        """Initialize enhanced multilingual intent detection patterns"""

        self.enhanced_patterns = {
            # Enhanced greeting patterns
            IntentType.GREETING: {
                "en": [
                    r"\b(hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening)\b",
                    r"\b(greetings|howdy|welcome|nice\s+to\s+meet)\b"
                ],
                "de": [
                    r"\b(hallo|guten\s+tag|guten\s+morgen|guten\s+abend)\b",
                    r"\b(grüß\s+gott|servus|moin)\b"
                ],
                "es": [
                    r"\b(hola|buenos\s+días|buenas\s+tardes|buenas\s+noches)\b",
                    r"\b(saludos|qué\s+tal)\b"
                ],
                "fr": [
                    r"\b(bonjour|bonsoir|salut|bonne\s+journée)\b",
                    r"\b(enchanté|ravi\s+de\s+vous\s+rencontrer)\b"
                ],
                "it": [
                    r"\b(ciao|buongiorno|buonasera|buona\s+giornata)\b",
                    r"\b(salve|piacere\s+di\s+conoscerla)\b"
                ]
            },

            # Existing reservation modification
            IntentType.EXISTING_RESERVATION_MODIFY: {
                "en": [
                    r"\b(change|modify|update|alter)\s+(my\s+)?(booking|reservation)\b",
                    r"\b(different\s+dates|change\s+dates|reschedule)\b",
                    r"\b(upgrade|downgrade)\s+(my\s+)?(room|suite)\b",
                    r"\b(extend|shorten)\s+(my\s+)?stay\b"
                ],
                "de": [
                    r"\b(ändern|modifizieren|anpassen)\s+(meine\s+)?(buchung|reservierung)\b",
                    r"\b(andere\s+termine|termine\s+ändern|verschieben)\b",
                    r"\b(upgrade|downgrade)\s+(mein\s+)?(zimmer|suite)\b"
                ],
                "es": [
                    r"\b(cambiar|modificar|actualizar)\s+(mi\s+)?(reserva|reservación)\b",
                    r"\b(fechas\s+diferentes|cambiar\s+fechas|reprogramar)\b",
                    r"\b(mejorar|degradar)\s+(mi\s+)?(habitación|suite)\b"
                ],
                "fr": [
                    r"\b(changer|modifier|mettre\s+à\s+jour)\s+(ma\s+)?réservation\b",
                    r"\b(dates\s+différentes|changer\s+dates|reprogrammer)\b",
                    r"\b(améliorer|dégrader)\s+(ma\s+)?(chambre|suite)\b"
                ],
                "it": [
                    r"\b(cambiare|modificare|aggiornare)\s+(la\s+mia\s+)?prenotazione\b",
                    r"\b(date\s+diverse|cambiare\s+date|riprogrammare)\b",
                    r"\b(migliorare|declassare)\s+(la\s+mia\s+)?(camera|suite)\b"
                ]
            },

            # Existing reservation cancellation
            IntentType.EXISTING_RESERVATION_CANCEL: {
                "en": [
                    r"\b(cancel|cancellation)\s+(my\s+)?(booking|reservation)\b",
                    r"\bcancel\s+(my\s+)?stay\b",
                    r"\b(refund|money\s+back)\b",
                    r"\b(don't\s+need|no\s+longer\s+need)\s+(the\s+)?(room|booking)\b"
                ],
                "de": [
                    r"\b(stornieren|kündigen)\s+(meine\s+)?(buchung|reservierung)\b",
                    r"\b(rückerstattung|geld\s+zurück)\b",
                    r"\b(brauche\s+nicht\s+mehr|nicht\s+mehr\s+nötig)\s+(das\s+)?(zimmer|buchung)\b"
                ],
                "es": [
                    r"\b(cancelar|anular)\s+(mi\s+)?(reserva|reservación)\b",
                    r"\b(reembolso|dinero\s+de\s+vuelta)\b",
                    r"\b(ya\s+no\s+necesito|no\s+necesito\s+más)\s+(la\s+)?(habitación|reserva)\b"
                ],
                "fr": [
                    r"\b(annuler|annulation)\s+(ma\s+)?réservation\b",
                    r"\b(remboursement|argent\s+en\s+retour)\b",
                    r"\b(n'ai\s+plus\s+besoin|plus\s+besoin)\s+(de\s+la\s+)?(chambre|réservation)\b"
                ],
                "it": [
                    r"\b(cancellare|annullare)\s+(la\s+mia\s+)?prenotazione\b",
                    r"\b(rimborso|soldi\s+indietro)\b",
                    r"\b(non\s+ho\s+più\s+bisogno|non\s+serve\s+più)\s+(della\s+)?(camera|prenotazione)\b"
                ]
            },

            # Upselling opportunities
            IntentType.UPSELLING_OPPORTUNITY: {
                "en": [
                    r"\b(upgrade|better|premium|luxury)\s+(room|suite|view)\b",
                    r"\b(executive|club|vip)\s+(floor|level|access)\b",
                    r"\b(ocean\s+view|sea\s+view|city\s+view|balcony)\b",
                    r"\b(larger|bigger)\s+(room|space)\b",
                    r"\b(special\s+occasion|anniversary|honeymoon|birthday)\b"
                ],
                "de": [
                    r"\b(upgrade|besser|premium|luxus)\s+(zimmer|suite|aussicht)\b",
                    r"\b(executive|club|vip)\s+(etage|level|zugang)\b",
                    r"\b(meerblick|stadtblick|balkon)\b",
                    r"\b(größer|größeres)\s+(zimmer|raum)\b"
                ],
                "es": [
                    r"\b(mejora|mejor|premium|lujo)\s+(habitación|suite|vista)\b",
                    r"\b(ejecutivo|club|vip)\s+(piso|nivel|acceso)\b",
                    r"\b(vista\s+al\s+mar|vista\s+a\s+la\s+ciudad|balcón)\b",
                    r"\b(más\s+grande|mayor)\s+(habitación|espacio)\b"
                ],
                "fr": [
                    r"\b(amélioration|meilleur|premium|luxe)\s+(chambre|suite|vue)\b",
                    r"\b(executive|club|vip)\s+(étage|niveau|accès)\b",
                    r"\b(vue\s+mer|vue\s+ville|balcon)\b",
                    r"\b(plus\s+grand|plus\s+spacieux)\s+(chambre|espace)\b"
                ],
                "it": [
                    r"\b(upgrade|migliore|premium|lusso)\s+(camera|suite|vista)\b",
                    r"\b(executive|club|vip)\s+(piano|livello|accesso)\b",
                    r"\b(vista\s+mare|vista\s+città|balcone)\b",
                    r"\b(più\s+grande|maggiore)\s+(camera|spazio)\b"
                ]
            },

            # Restaurant booking
            IntentType.RESTAURANT_BOOKING: {
                "en": [
                    r"\b(restaurant|dining|dinner|lunch|breakfast)\s+(reservation|booking)\b",
                    r"\b(book|reserve)\s+(a\s+)?table\b",
                    r"\b(menu|special\s+menu|wine\s+list)\b",
                    r"\b(restaurant\s+hours|dining\s+hours)\b"
                ],
                "de": [
                    r"\b(restaurant|essen|abendessen|mittagessen|frühstück)\s+(reservierung|buchung)\b",
                    r"\b(tisch\s+reservieren|tisch\s+buchen)\b",
                    r"\b(speisekarte|menü|weinkarte)\b"
                ],
                "es": [
                    r"\b(restaurante|cena|almuerzo|desayuno)\s+(reserva|reservación)\b",
                    r"\b(reservar|hacer\s+reserva)\s+(mesa|table)\b",
                    r"\b(menú|carta|lista\s+de\s+vinos)\b"
                ],
                "fr": [
                    r"\b(restaurant|dîner|déjeuner|petit\s+déjeuner)\s+réservation\b",
                    r"\b(réserver|faire\s+une\s+réservation)\s+(table|une\s+table)\b",
                    r"\b(menu|carte|carte\s+des\s+vins)\b"
                ],
                "it": [
                    r"\b(ristorante|cena|pranzo|colazione)\s+prenotazione\b",
                    r"\b(prenotare|riservare)\s+(tavolo|un\s+tavolo)\b",
                    r"\b(menu|carta|lista\s+vini)\b"
                ]
            },

            # Spa booking
            IntentType.SPA_BOOKING: {
                "en": [
                    r"\b(spa|massage|facial|treatment)\s+(booking|appointment|reservation)\b",
                    r"\b(wellness|relaxation|therapy)\b",
                    r"\b(manicure|pedicure|beauty\s+treatment)\b",
                    r"\b(spa\s+hours|spa\s+menu|spa\s+services)\b"
                ],
                "de": [
                    r"\b(spa|massage|gesichtsbehandlung|behandlung)\s+(termin|reservierung)\b",
                    r"\b(wellness|entspannung|therapie)\b",
                    r"\b(maniküre|pediküre|schönheitsbehandlung)\b"
                ],
                "es": [
                    r"\b(spa|masaje|facial|tratamiento)\s+(cita|reserva)\b",
                    r"\b(bienestar|relajación|terapia)\b",
                    r"\b(manicura|pedicura|tratamiento\s+de\s+belleza)\b"
                ],
                "fr": [
                    r"\b(spa|massage|facial|traitement)\s+(rendez-vous|réservation)\b",
                    r"\b(bien-être|relaxation|thérapie)\b",
                    r"\b(manucure|pédicure|soin\s+de\s+beauté)\b"
                ],
                "it": [
                    r"\b(spa|massaggio|trattamento\s+viso|trattamento)\s+(appuntamento|prenotazione)\b",
                    r"\b(benessere|relax|terapia)\b",
                    r"\b(manicure|pedicure|trattamento\s+di\s+bellezza)\b"
                ]
            },

            # Room service
            IntentType.ROOM_SERVICE: {
                "en": [
                    r"\b(room\s+service|in-room\s+dining)\b",
                    r"\b(order\s+food|food\s+delivery|meal\s+to\s+room)\b",
                    r"\b(room\s+service\s+menu|in-room\s+menu)\b",
                    r"\b(deliver\s+to\s+room|bring\s+to\s+room)\b"
                ],
                "de": [
                    r"\b(zimmerservice|room\s+service)\b",
                    r"\b(essen\s+bestellen|essen\s+aufs\s+zimmer)\b",
                    r"\b(zimmerservice\s+karte|room\s+service\s+menü)\b"
                ],
                "es": [
                    r"\b(servicio\s+a\s+la\s+habitación|room\s+service)\b",
                    r"\b(pedir\s+comida|comida\s+a\s+la\s+habitación)\b",
                    r"\b(menú\s+de\s+habitación|carta\s+room\s+service)\b"
                ],
                "fr": [
                    r"\b(service\s+en\s+chambre|room\s+service)\b",
                    r"\b(commander\s+à\s+manger|repas\s+en\s+chambre)\b",
                    r"\b(menu\s+chambre|carte\s+room\s+service)\b"
                ],
                "it": [
                    r"\b(servizio\s+in\s+camera|room\s+service)\b",
                    r"\b(ordinare\s+cibo|cibo\s+in\s+camera)\b",
                    r"\b(menu\s+camera|carta\s+room\s+service)\b"
                ]
            },

            # Complaint/Feedback
            IntentType.COMPLAINT_FEEDBACK: {
                "en": [
                    r"\b(complain|complaint|problem|issue|dissatisfied)\b",
                    r"\b(not\s+happy|unhappy|disappointed|frustrated)\b",
                    r"\b(bad\s+service|poor\s+service|terrible|awful)\b",
                    r"\b(feedback|review|comment|suggestion)\b"
                ],
                "de": [
                    r"\b(beschwerde|problem|unzufrieden|ärger)\b",
                    r"\b(nicht\s+zufrieden|enttäuscht|frustriert)\b",
                    r"\b(schlechter\s+service|schlechte\s+bedienung)\b"
                ],
                "es": [
                    r"\b(queja|problema|insatisfecho|molesto)\b",
                    r"\b(no\s+contento|descontento|decepcionado|frustrado)\b",
                    r"\b(mal\s+servicio|servicio\s+terrible)\b"
                ],
                "fr": [
                    r"\b(plainte|problème|insatisfait|mécontent)\b",
                    r"\b(pas\s+content|déçu|frustré)\b",
                    r"\b(mauvais\s+service|service\s+terrible)\b"
                ],
                "it": [
                    r"\b(reclamo|problema|insoddisfatto|scontento)\b",
                    r"\b(non\s+contento|deluso|frustrato)\b",
                    r"\b(cattivo\s+servizio|servizio\s+terribile)\b"
                ]
            },

            # Transfer to operator
            IntentType.TRANSFER_TO_OPERATOR: {
                "en": [
                    r"\b(speak\s+to|talk\s+to)\s+(human|person|operator|agent|representative)\b",
                    r"\b(transfer\s+me|connect\s+me)\s+to\b",
                    r"\b(real\s+person|live\s+agent)\b",
                    r"\b(human\s+help|human\s+assistance)\b"
                ],
                "de": [
                    r"\b(sprechen\s+mit|reden\s+mit)\s+(mensch|person|operator|mitarbeiter)\b",
                    r"\b(verbinden\s+sie\s+mich|weiterleiten)\b",
                    r"\b(echte\s+person|live\s+agent)\b"
                ],
                "es": [
                    r"\b(hablar\s+con|conversar\s+con)\s+(humano|persona|operador|agente)\b",
                    r"\b(transferir|conectar)\s+con\b",
                    r"\b(persona\s+real|agente\s+en\s+vivo)\b"
                ],
                "fr": [
                    r"\b(parler\s+à|discuter\s+avec)\s+(humain|personne|opérateur|agent)\b",
                    r"\b(transférer|connecter)\s+à\b",
                    r"\b(vraie\s+personne|agent\s+en\s+direct)\b"
                ],
                "it": [
                    r"\b(parlare\s+con|conversare\s+con)\s+(umano|persona|operatore|agente)\b",
                    r"\b(trasferire|collegare)\s+a\b",
                    r"\b(persona\s+reale|agente\s+dal\s+vivo)\b"
                ]
            },

            # Concierge services
            IntentType.CONCIERGE_SERVICES: {
                "en": [
                    r"\b(concierge|local\s+attractions|recommendations)\b",
                    r"\b(tickets|tours|transportation|taxi|directions)\b",
                    r"\b(events|shows|theater|museums)\b",
                    r"\b(help\s+with|assistance\s+with|arrange)\b"
                ],
                "de": [
                    r"\b(concierge|lokale\s+attraktionen|empfehlungen)\b",
                    r"\b(tickets|touren|transport|taxi|wegbeschreibung)\b",
                    r"\b(veranstaltungen|shows|theater|museen)\b"
                ],
                "es": [
                    r"\b(concierge|atracciones\s+locales|recomendaciones)\b",
                    r"\b(boletos|tours|transporte|taxi|direcciones)\b",
                    r"\b(eventos|espectáculos|teatro|museos)\b"
                ],
                "fr": [
                    r"\b(concierge|attractions\s+locales|recommandations)\b",
                    r"\b(billets|tours|transport|taxi|directions)\b",
                    r"\b(événements|spectacles|théâtre|musées)\b"
                ],
                "it": [
                    r"\b(concierge|attrazioni\s+locali|raccomandazioni)\b",
                    r"\b(biglietti|tour|trasporto|taxi|indicazioni)\b",
                    r"\b(eventi|spettacoli|teatro|musei)\b"
                ]
            },

            # Standard intents (enhanced)
            IntentType.BOOKING_INQUIRY: {
                "en": [
                    r"\b(book|reserve|availability|available)\s+(room|suite)\b",
                    r"\b(check\s+in|check\s+out|dates|nights)\b",
                    r"\b(price|cost|rate|how\s+much)\b"
                ],
                "de": [
                    r"\b(buchen|reservieren|verfügbarkeit)\s+(zimmer|suite)\b",
                    r"\b(check\s+in|check\s+out|termine|nächte)\b",
                    r"\b(preis|kosten|tarif|wie\s+viel)\b"
                ],
                "es": [
                    r"\b(reservar|disponibilidad)\s+(habitación|suite)\b",
                    r"\b(check\s+in|check\s+out|fechas|noches)\b",
                    r"\b(precio|costo|tarifa|cuánto)\b"
                ],
                "fr": [
                    r"\b(réserver|disponibilité)\s+(chambre|suite)\b",
                    r"\b(check\s+in|check\s+out|dates|nuits)\b",
                    r"\b(prix|coût|tarif|combien)\b"
                ],
                "it": [
                    r"\b(prenotare|disponibilità)\s+(camera|suite)\b",
                    r"\b(check\s+in|check\s+out|date|notti)\b",
                    r"\b(prezzo|costo|tariffa|quanto)\b"
                ]
            },

            IntentType.END_CALL: {
                "en": [
                    r"\b(goodbye|bye|see\s+you|thank\s+you|thanks|end\s+call)\b",
                    r"\b(that's\s+all|all\s+done|finished|complete)\b"
                ],
                "de": [
                    r"\b(auf\s+wiedersehen|tschüss|danke|anruf\s+beenden)\b",
                    r"\b(das\s+war's|fertig|abgeschlossen)\b"
                ],
                "es": [
                    r"\b(adiós|hasta\s+luego|gracias|terminar\s+llamada)\b",
                    r"\b(eso\s+es\s+todo|terminado|completo)\b"
                ],
                "fr": [
                    r"\b(au\s+revoir|à\s+bientôt|merci|terminer\s+appel)\b",
                    r"\b(c'est\s+tout|fini|terminé)\b"
                ],
                "it": [
                    r"\b(arrivederci|ciao|grazie|terminare\s+chiamata)\b",
                    r"\b(è\s+tutto|finito|completato)\b"
                ]
            }
        }

    def detect_multiple_intents(
        self,
        utterance: str,
        language: str = "en",
        conversation_context: Optional[Dict[str, Any]] = None
    ) -> MultiIntentDetectionResult:
        """
        Enhanced multi-intent detection for Sprint 3

        Args:
            utterance: User's text input
            language: Language code
            conversation_context: Previous conversation context

        Returns:
            MultiIntentDetectionResult with all detected intents
        """
        start_time = time.time()

        try:
            # Normalize utterance
            normalized_utterance = utterance.lower().strip()

            # Detect all possible intents
            detected_intents = []

            # Run pattern-based detection for all intents
            for intent_type in IntentType:
                confidence = self._calculate_pattern_confidence(
                    normalized_utterance, intent_type, language
                )

                if confidence > 0.2:  # Lower threshold for multi-intent
                    detected_intent = DetectedIntent(
                        intent=intent_type,
                        confidence=confidence,
                        confidence_level=ConfidenceLevel.LOW,  # Will be auto-calculated
                        parameters=self._extract_parameters(normalized_utterance, intent_type),
                        source_detector="enhanced_pattern_detector"
                    )
                    detected_intents.append(detected_intent)

            # Sort by confidence and priority
            detected_intents.sort(
                key=lambda x: (x.confidence, self.intent_priorities.get(x.intent, 0)),
                reverse=True
            )

            # Determine primary intent
            primary_intent = detected_intents[0] if detected_intents else None

            # Check for ambiguity
            ambiguous = len([i for i in detected_intents if i.confidence > 0.6]) > 1

            # Determine if clarification is needed
            requires_clarification = (
                ambiguous or
                (primary_intent and primary_intent.confidence < 0.6) or
                not detected_intents
            )

            # Generate clarification message if needed
            clarification_message = None
            if requires_clarification:
                clarification_message = self._generate_clarification_message(
                    detected_intents, language
                )

            processing_time = (time.time() - start_time) * 1000

            result = MultiIntentDetectionResult(
                utterance=utterance,
                detected_intents=detected_intents,
                primary_intent=primary_intent,
                language=language,
                processing_time_ms=processing_time,
                ambiguous=ambiguous,
                requires_clarification=requires_clarification,
                clarification_message=clarification_message
            )

            # Update statistics
            self.stats["total_detections"] += 1
            self.language_stats[language] += 1

            if primary_intent:
                self.stats[f"intent_{primary_intent.intent.value}"] += 1
                self.confidence_stats[primary_intent.confidence_level.value] += 1

            logger.info(
                "multi_intent_detection_completed",
                utterance_length=len(utterance),
                detected_intents_count=len(detected_intents),
                primary_intent=primary_intent.intent.value if primary_intent else None,
                primary_confidence=primary_intent.confidence if primary_intent else 0.0,
                ambiguous=ambiguous,
                processing_time_ms=processing_time,
                language=language
            )

            return result

        except Exception as e:
            logger.error("multi_intent_detection_error", error=str(e), utterance=utterance)

            # Return fallback result
            return MultiIntentDetectionResult(
                utterance=utterance,
                detected_intents=[],
                primary_intent=None,
                language=language,
                processing_time_ms=(time.time() - start_time) * 1000,
                ambiguous=False,
                requires_clarification=True,
                clarification_message="I'm sorry, I didn't understand that. Could you please rephrase?"
            )

    def _calculate_pattern_confidence(
        self,
        utterance: str,
        intent: IntentType,
        language: str
    ) -> float:
        """Calculate confidence score for pattern matching"""

        if intent not in self.enhanced_patterns:
            return 0.0

        language_patterns = self.enhanced_patterns[intent].get(language, [])
        if not language_patterns:
            # Fallback to English patterns
            language_patterns = self.enhanced_patterns[intent].get("en", [])

        if not language_patterns:
            return 0.0

        max_confidence = 0.0

        for pattern in language_patterns:
            try:
                match = re.search(pattern, utterance, re.IGNORECASE)
                if match:
                    # Base confidence from match
                    base_confidence = 0.7

                    # Boost confidence based on match quality
                    match_length = len(match.group(0))
                    utterance_length = len(utterance)
                    coverage = match_length / utterance_length

                    # Apply coverage boost
                    confidence = base_confidence + (coverage * 0.3)

                    # Apply intent-specific boosts
                    confidence = self._apply_intent_specific_boosts(
                        confidence, intent, utterance
                    )

                    max_confidence = max(max_confidence, min(confidence, 1.0))

            except re.error:
                logger.warning("invalid_regex_pattern", pattern=pattern, intent=intent.value)
                continue

        return max_confidence

    def _apply_intent_specific_boosts(
        self,
        base_confidence: float,
        intent: IntentType,
        utterance: str
    ) -> float:
        """Apply intent-specific confidence boosts"""

        confidence = base_confidence

        # High priority intents get confidence boost
        if intent in [IntentType.END_CALL, IntentType.TRANSFER_TO_OPERATOR]:
            confidence += 0.1

        # Booking-related intents get boost if dates/numbers mentioned
        if intent in [IntentType.BOOKING_INQUIRY, IntentType.EXISTING_RESERVATION_MODIFY]:
            if re.search(r'\b(\d{1,2}[/-]\d{1,2}|\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december))\b', utterance, re.IGNORECASE):
                confidence += 0.15
            if re.search(r'\b(\d+\s+(night|day|week)s?)\b', utterance, re.IGNORECASE):
                confidence += 0.1

        # Service-related intents get boost with time mentions
        if intent in [IntentType.RESTAURANT_BOOKING, IntentType.SPA_BOOKING, IntentType.ROOM_SERVICE]:
            if re.search(r'\b(\d{1,2}:\d{2}|\d{1,2}\s?(am|pm)|morning|afternoon|evening|tonight)\b', utterance, re.IGNORECASE):
                confidence += 0.1

        # Complaint intents get boost with negative sentiment
        if intent == IntentType.COMPLAINT_FEEDBACK:
            negative_words = ['not', 'no', 'never', 'bad', 'terrible', 'awful', 'poor', 'worst']
            negative_count = sum(1 for word in negative_words if word in utterance.lower())
            confidence += min(negative_count * 0.05, 0.2)

        return min(confidence, 1.0)

    def _extract_parameters(self, utterance: str, intent: IntentType) -> Dict[str, Any]:
        """Extract parameters relevant to the detected intent"""

        parameters = {}

        # Extract dates
        date_match = re.search(r'\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b', utterance)
        if date_match:
            parameters['date'] = date_match.group(1)

        # Extract times
        time_match = re.search(r'\b(\d{1,2}:\d{2}(?:\s?[ap]m)?|\d{1,2}\s?[ap]m)\b', utterance, re.IGNORECASE)
        if time_match:
            parameters['time'] = time_match.group(1)

        # Extract numbers
        number_match = re.search(r'\b(\d+)\b', utterance)
        if number_match:
            parameters['number'] = int(number_match.group(1))

        # Extract room types
        room_types = ['single', 'double', 'twin', 'suite', 'deluxe', 'standard', 'executive', 'premium']
        for room_type in room_types:
            if room_type in utterance.lower():
                parameters['room_type'] = room_type
                break

        # Intent-specific parameter extraction
        if intent == IntentType.RESTAURANT_BOOKING:
            # Extract party size
            party_match = re.search(r'\b(for\s+)?(\d+)\s+(people|person|guest|pax)\b', utterance, re.IGNORECASE)
            if party_match:
                parameters['party_size'] = int(party_match.group(2))

        elif intent == IntentType.SPA_BOOKING:
            # Extract service types
            spa_services = ['massage', 'facial', 'manicure', 'pedicure', 'therapy']
            for service in spa_services:
                if service in utterance.lower():
                    parameters['service_type'] = service
                    break

        elif intent in [IntentType.EXISTING_RESERVATION_MODIFY, IntentType.EXISTING_RESERVATION_CANCEL]:
            # Extract confirmation numbers
            conf_match = re.search(r'\b([A-Z0-9]{6,})\b', utterance)
            if conf_match:
                parameters['confirmation_number'] = conf_match.group(1)

        return parameters

    def _generate_clarification_message(
        self,
        detected_intents: List[DetectedIntent],
        language: str
    ) -> str:
        """Generate clarification message when intent is ambiguous"""

        clarification_templates = {
            "en": {
                "no_intent": "I'm sorry, I didn't understand that. Could you please tell me how I can help you?",
                "multiple_intents": "I understand you might want to {options}. Which one would you like to do first?",
                "low_confidence": "I think you want to {intent}, but I'm not sure. Is that correct?"
            },
            "de": {
                "no_intent": "Entschuldigung, das habe ich nicht verstanden. Können Sie mir bitte sagen, wie ich Ihnen helfen kann?",
                "multiple_intents": "Ich verstehe, dass Sie {options} möchten. Was möchten Sie zuerst tun?",
                "low_confidence": "Ich denke, Sie möchten {intent}, aber ich bin mir nicht sicher. Ist das richtig?"
            },
            "es": {
                "no_intent": "Lo siento, no entendí eso. ¿Podría decirme cómo puedo ayudarle?",
                "multiple_intents": "Entiendo que podría querer {options}. ¿Cuál le gustaría hacer primero?",
                "low_confidence": "Creo que quiere {intent}, pero no estoy seguro. ¿Es correcto?"
            },
            "fr": {
                "no_intent": "Désolé, je n'ai pas compris. Pourriez-vous me dire comment je peux vous aider?",
                "multiple_intents": "Je comprends que vous pourriez vouloir {options}. Que souhaitez-vous faire en premier?",
                "low_confidence": "Je pense que vous voulez {intent}, mais je ne suis pas sûr. Est-ce correct?"
            },
            "it": {
                "no_intent": "Mi dispiace, non ho capito. Potreste dirmi come posso aiutarvi?",
                "multiple_intents": "Capisco che potreste voler {options}. Cosa vorreste fare per prima?",
                "low_confidence": "Penso che vogliate {intent}, ma non ne sono sicuro. È corretto?"
            }
        }

        templates = clarification_templates.get(language, clarification_templates["en"])

        if not detected_intents:
            return templates["no_intent"]

        high_confidence_intents = [i for i in detected_intents if i.confidence > 0.6]

        if len(high_confidence_intents) > 1:
            # Multiple high confidence intents
            intent_descriptions = [self._get_intent_description(i.intent, language) for i in high_confidence_intents[:3]]
            options = " or ".join(intent_descriptions)
            return templates["multiple_intents"].format(options=options)

        elif detected_intents[0].confidence < 0.6:
            # Low confidence primary intent
            intent_desc = self._get_intent_description(detected_intents[0].intent, language)
            return templates["low_confidence"].format(intent=intent_desc)

        return templates["no_intent"]

    def _get_intent_description(self, intent: IntentType, language: str) -> str:
        """Get human-readable description of intent"""

        descriptions = {
            "en": {
                IntentType.BOOKING_INQUIRY: "make a reservation",
                IntentType.EXISTING_RESERVATION_MODIFY: "modify your reservation",
                IntentType.EXISTING_RESERVATION_CANCEL: "cancel your reservation",
                IntentType.RESTAURANT_BOOKING: "make a restaurant reservation",
                IntentType.SPA_BOOKING: "book a spa appointment",
                IntentType.ROOM_SERVICE: "order room service",
                IntentType.UPSELLING_OPPORTUNITY: "upgrade your room",
                IntentType.CONCIERGE_SERVICES: "get concierge assistance",
                IntentType.COMPLAINT_FEEDBACK: "provide feedback",
                IntentType.TRANSFER_TO_OPERATOR: "speak to a representative",
                IntentType.REQUEST_INFO: "get information",
                IntentType.END_CALL: "end the call"
            },
            "de": {
                IntentType.BOOKING_INQUIRY: "eine Reservierung machen",
                IntentType.EXISTING_RESERVATION_MODIFY: "Ihre Reservierung ändern",
                IntentType.EXISTING_RESERVATION_CANCEL: "Ihre Reservierung stornieren",
                IntentType.RESTAURANT_BOOKING: "einen Restauranttisch reservieren",
                IntentType.SPA_BOOKING: "einen Spa-Termin buchen",
                IntentType.ROOM_SERVICE: "Zimmerservice bestellen",
                IntentType.UPSELLING_OPPORTUNITY: "Ihr Zimmer upgraden",
                IntentType.CONCIERGE_SERVICES: "Concierge-Hilfe bekommen",
                IntentType.COMPLAINT_FEEDBACK: "Feedback geben",
                IntentType.TRANSFER_TO_OPERATOR: "mit einem Mitarbeiter sprechen",
                IntentType.REQUEST_INFO: "Informationen erhalten",
                IntentType.END_CALL: "das Gespräch beenden"
            }
        }

        lang_descriptions = descriptions.get(language, descriptions["en"])
        return lang_descriptions.get(intent, intent.value.replace("_", " "))

    def get_statistics(self) -> Dict[str, Any]:
        """Get enhanced detection statistics"""
        return {
            "total_detections": self.stats["total_detections"],
            "by_intent": {k.replace("intent_", ""): v for k, v in self.stats.items() if k.startswith("intent_")},
            "by_confidence": dict(self.confidence_stats),
            "by_language": dict(self.language_stats),
            "supported_languages": ["en", "de", "es", "fr", "it"],
            "supported_intents": [intent.value for intent in IntentType],
            "multi_intent_capable": True,
            "clarification_support": True
        }