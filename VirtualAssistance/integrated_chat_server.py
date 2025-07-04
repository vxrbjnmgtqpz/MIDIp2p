#!/usr/bin/env python3
"""
Integrated Music Chat Server
Combines all three music generation models into a unified chatbot interface
"""

from flask import Flask, request, jsonify, Response, send_from_directory, session
from flask_cors import CORS
import json
import time
import os
import re
import asyncio
import uuid
import random
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Import our three models
from chord_progression_model import ChordProgressionModel
from individual_chord_model import IndividualChordModel
import sys
sys.path.append('./TheoryEngine')
from enhanced_solfege_theory_engine import EnhancedSolfegeTheoryEngine
from voice_leading_engine import EnhancedVoiceLeadingEngine

app = Flask(__name__)
app.secret_key = 'music_theory_chat_secret_key'  # For session management
CORS(app, supports_credentials=True)

@dataclass
class ConversationContext:
    """Stores conversation context for follow-up requests"""
    last_response: Dict[str, Any]
    last_progression: List[str]
    last_emotion: str
    last_style: str
    last_mode: str
    session_id: str
    timestamp: float

class ConversationMemory:
    """Manages conversation context across requests"""
    
    def __init__(self):
        self.sessions = {}
        self.max_session_age = 3600  # 1 hour
    
    def get_session_id(self):
        """Get or create session ID"""
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        return session['session_id']
    
    def store_context(self, session_id: str, response_data: Dict[str, Any]):
        """Store conversation context"""
        print(f"DEBUG: Storing context for session {session_id}")
        print(f"DEBUG: Response data keys: {list(response_data.keys())}")
        print(f"DEBUG: Chords in response: {response_data.get('chords', [])}")
        
        # Extract conversation data properly
        chords = response_data.get('chords', [])
        
        # Extract primary emotion from emotions dict
        emotions = response_data.get('emotions', {})
        primary_emotion = max(emotions.items(), key=lambda x: x[1])[0] if emotions else ""
        
        # Extract style and mode from primary_result
        primary_result = response_data.get('primary_result', {})
        style = primary_result.get('genre', '')
        mode = primary_result.get('primary_mode', '')
        
        # Get existing context to preserve data
        existing_context = self.get_context(session_id)
        
        context = ConversationContext(
            last_response=response_data,
            last_progression=chords or (existing_context.last_progression if existing_context else []),
            last_emotion=primary_emotion or (existing_context.last_emotion if existing_context else ""),
            last_style=style or (existing_context.last_style if existing_context else ""),
            last_mode=mode or (existing_context.last_mode if existing_context else ""),
            session_id=session_id,
            timestamp=time.time()
        )
        self.sessions[session_id] = context
        print(f"DEBUG: Stored progression: {context.last_progression}")
        print(f"DEBUG: Stored emotion: {context.last_emotion}")
        print(f"DEBUG: Stored mode: {context.last_mode}")
    
    def get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Retrieve conversation context"""
        print(f"DEBUG: Getting context for session {session_id}")
        print(f"DEBUG: Available sessions: {list(self.sessions.keys())}")
        
        context = self.sessions.get(session_id)
        if context and (time.time() - context.timestamp) < self.max_session_age:
            print(f"DEBUG: Found valid context with progression: {context.last_progression}")
            return context
        elif context:
            # Clean up expired session
            print(f"DEBUG: Context expired, cleaning up")
            del self.sessions[session_id]
        else:
            print(f"DEBUG: No context found for session")
        return None
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        current_time = time.time()
        expired_sessions = [
            sid for sid, ctx in self.sessions.items()
            if (current_time - ctx.timestamp) > self.max_session_age
        ]
        for sid in expired_sessions:
            del self.sessions[sid]

@dataclass
class UserIntent:
    """Represents the classified intent of a user message"""
    primary_intent: str
    confidence: float
    extracted_params: Dict[str, Any]
    suggested_models: List[str]

class IntentClassifier:
    """Classifies user intents and determines which models to use"""
    
    def __init__(self):
        self.intent_patterns = {
            "emotional_progression": {
                "patterns": [
                    r"i\s+(feel|am\s+feeling|want\s+something)",
                    r"(happy|sad|angry|romantic|nostalgic|excited|melancholy|joyful|peaceful|dramatic|energetic|soulful).*progression",
                    r"make.*sound|want.*that.*sounds|create.*mood",
                    r"feeling\s+(like|very|really|quite|somewhat)",
                    r"(uplifting|depressing|calming|aggressive|tender|mysterious|bright|dark)"
                ],
                "models": ["progression", "individual", "theory"],
                "params": ["emotion", "style", "length"]
            },
            "individual_chord": {
                "patterns": [
                    r"what\s+chord|which\s+chord|chord\s+for|chord\s+that",
                    r"single\s+chord|one\s+chord|individual\s+chord",
                    r"best\s+chord\s+for|chord\s+represents"
                ],
                "models": ["individual", "theory"],
                "params": ["emotion", "context"]
            },
            "individual_analysis": {
                "patterns": [
                    r"show.*me.*individual.*chord.*emotions?",
                    r"individual.*chord.*emotions?",
                    r"analyze.*each.*chord",
                    r"emotions?.*for.*each.*chord",
                    r"breakdown.*of.*chord.*emotions?",
                    r"ask.*for.*details"
                ],
                "models": ["individual"],
                "params": ["progression_context"]
            },
            "theory_request": {
                "patterns": [
                    r"(jazz|blues|classical|rock|pop|folk|rnb|cinematic)\s+(progression|chord|style)",
                    r"(ionian|dorian|phrygian|lydian|mixolydian|aeolian|locrian)\s+(mode|scale)",
                    r"theory|analysis|explain|why|how.*work",
                    r"generate.*in\s+(jazz|blues|classical|rock|pop|folk)",
                    r"show.*me.*in\s+(major|minor|dorian|phrygian)"
                ],
                "models": ["theory", "progression"],
                "params": ["style", "mode", "length", "analysis_type"]
            },
            "comparison": {
                "patterns": [
                    r"compare|versus|vs|different.*style",
                    r"how.*sound.*in|what.*if.*were",
                    r"show.*me.*different|try.*in.*style",
                    r"(jazz|blues|classical).*vs.*(jazz|blues|classical)"
                ],
                "models": ["theory", "progression", "individual"],
                "params": ["styles", "emotion", "comparison_type"]
            },
            "educational": {
                "patterns": [
                    r"explain|why.*does|how.*work|what.*makes",
                    r"teach.*me|learn.*about|understand",
                    r"difference.*between|what.*is.*the",
                    r"music.*theory|harmonic.*function"
                ],
                "models": ["theory", "individual"],
                "params": ["concept", "depth_level"]
            }
        }
        
        self.emotion_keywords = [
            "happy", "sad", "angry", "fearful", "disgusted", "surprised", 
            "trusting", "anticipation", "joy", "sadness", "fear", "anger",
            "disgust", "surprise", "trust", "shame", "love", "envy",
            "romantic", "melancholy", "energetic", "peaceful", "dramatic",
            "nostalgic", "uplifting", "mysterious", "bright", "dark",
            "tender", "aggressive", "calming", "exciting", "soulful",
            "transcendent", "mystical", "ethereal", "otherworldly", "cosmic",
            "divine", "spiritual", "enlightened", "transcendental", "sublime",
            "celestial", "dreamlike", "lucid", "visionary", "floating",
            "weightless", "ego death", "dissolution", "sacred", "dissonant"
        ]
        
        self.style_keywords = [
            "jazz", "blues", "classical", "pop", "rock", "folk", "rnb", "cinematic"
        ]
        
        self.mode_keywords = [
            "ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian",
            "major", "minor"
        ]
    
    def classify(self, text: str, context: Optional[ConversationContext] = None) -> UserIntent:
        """Classify user intent and extract parameters with conversation context"""
        text_lower = text.lower().strip()
        
        # Score each intent type
        intent_scores = {}
        extracted_params = {}
        
        for intent_type, intent_data in self.intent_patterns.items():
            score = 0
            for pattern in intent_data["patterns"]:
                if re.search(pattern, text_lower):
                    score += 1
            intent_scores[intent_type] = score
        
        # Boost individual_analysis if context suggests it and patterns match
        if context and context.last_progression and len(context.last_progression) > 0:
            if intent_scores.get("individual_analysis", 0) > 0:
                intent_scores["individual_analysis"] += 2  # Boost this intent
                extracted_params["context_progression"] = context.last_progression
                extracted_params["context_emotion"] = context.last_emotion
        
        # Determine primary intent
        if not intent_scores or max(intent_scores.values()) == 0:
            primary_intent = "emotional_progression"  # Default fallback
            confidence = 0.3
        else:
            primary_intent = max(intent_scores, key=intent_scores.get)
            confidence = min(intent_scores[primary_intent] / 3.0, 1.0)
        
        # Extract parameters
        extracted_params.update(self._extract_parameters(text_lower))
        
        # Get suggested models
        suggested_models = self.intent_patterns[primary_intent]["models"]
        
        return UserIntent(
            primary_intent=primary_intent,
            confidence=confidence,
            extracted_params=extracted_params,
            suggested_models=suggested_models
        )
    
    def _extract_parameters(self, text: str) -> Dict[str, Any]:
        """Extract musical parameters from user text"""
        params = {}
        text_lower = text.lower()
        
        # Extract emotions
        emotion_keywords = {
            'happy': ['happy', 'joy', 'joyful', 'cheerful', 'bright', 'upbeat', 'positive'],
            'sad': ['sad', 'melancholy', 'sorrowful', 'depressed', 'down', 'blue', 'mournful'],
            'angry': ['angry', 'rage', 'furious', 'mad', 'aggressive', 'intense', 'harsh'],
            'fear': ['scary', 'frightening', 'tense', 'anxious', 'nervous', 'worried', 'dark'],
            'love': ['love', 'romantic', 'tender', 'affectionate', 'warm', 'intimate'],
            'wonder': ['wonder', 'awe', 'mysterious', 'magical', 'ethereal', 'transcendent'],
            'trust': ['trust', 'confidence', 'steady', 'reliable', 'stable', 'grounded'],
            'surprise': ['surprise', 'unexpected', 'shocking', 'sudden', 'startling'],
            'transcendence': ['transcendent', 'mystical', 'ethereal', 'otherworldly', 'cosmic', 'divine', 'spiritual', 'enlightened', 'transcendental', 'sublime', 'celestial', 'dreamlike', 'lucid', 'visionary', 'floating', 'weightless', 'ego death', 'dissolution', 'sacred', 'dissonant']
        }
        
        detected_emotions = []
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                detected_emotions.append(emotion)
        
        if detected_emotions:
            params['primary_emotion'] = detected_emotions[0]
            params['detected_emotions'] = detected_emotions
        
        # Extract consonant/dissonant preferences
        consonant_keywords = ['consonant', 'smooth', 'peaceful', 'gentle', 'soft', 'harmonious', 'stable', 'resolved']
        dissonant_keywords = ['dissonant', 'tense', 'harsh', 'edgy', 'rough', 'complex', 'unresolved', 'tension']
        moderate_keywords = ['moderate', 'balanced', 'medium', 'some tension', 'bit of edge']
        
        if any(keyword in text_lower for keyword in consonant_keywords):
            params['consonant_dissonant_preference'] = 'consonant'
        elif any(keyword in text_lower for keyword in dissonant_keywords):
            params['consonant_dissonant_preference'] = 'dissonant'
        elif any(keyword in text_lower for keyword in moderate_keywords):
            params['consonant_dissonant_preference'] = 'moderate'
        
        # Extract modes
        mode_keywords = {
            'major': ['major', 'ionian', 'bright', 'happy'],
            'minor': ['minor', 'aeolian', 'sad', 'dark'],
            'dorian': ['dorian', 'folk', 'modal'],
            'mixolydian': ['mixolydian', 'bluesy', 'dominant'],
            'lydian': ['lydian', 'dreamy', 'floating'],
            'phrygian': ['phrygian', 'spanish', 'exotic']
        }
        
        for mode, keywords in mode_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                params['primary_mode'] = mode.capitalize()
                break
        
        # Extract styles
        style_keywords = {
            'jazz': ['jazz', 'swing', 'bebop', 'smooth jazz'],
            'classical': ['classical', 'baroque', 'romantic', 'orchestral'],
            'pop': ['pop', 'commercial', 'radio', 'mainstream'],
            'rock': ['rock', 'guitar', 'electric', 'power'],
            'blues': ['blues', 'twelve bar', 'shuffle'],
            'folk': ['folk', 'acoustic', 'traditional']
        }
        
        for style, keywords in style_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                params['primary_style'] = style.capitalize()
                break
        
        # Extract numbers
        import re
        numbers = re.findall(r'\d+', text)
        if numbers:
            params['num_options'] = min(int(numbers[0]), 10)  # Cap at 10 options
            if len(numbers) > 1:
                params['length'] = min(int(numbers[1]), 16)  # Cap at 16 chord progressions
        
        return params

class ResponseSynthesizer:
    """Combines results from multiple models into unified responses"""
    
    def __init__(self):
        self.response_templates = {
            "emotional_progression": self._synthesize_emotional_progression,
            "individual_chord": self._synthesize_single_chord,
            "individual_analysis": self._synthesize_individual_analysis,
            "theory_request": self._synthesize_theory_request,
            "comparison": self._synthesize_comparison,
            "educational": self._synthesize_educational
        }
    
    def synthesize(self, intent: UserIntent, model_results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize a unified response from model results"""
        synthesizer = self.response_templates.get(intent.primary_intent, self._synthesize_default)
        return synthesizer(intent, model_results)
    
    def _synthesize_emotional_progression(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for emotional progression requests"""
        progression_result = results.get("progression", {})
        individual_result = results.get("individual", {})
        theory_result = results.get("theory", {})
        
        # Build primary response
        chords = progression_result.get("chords", [])
        emotions = progression_result.get("emotion_weights", {})
        
        # Create comprehensive message
        message_parts = []
        
        if chords:
            message_parts.append(f"🎼 **{' → '.join(chords)}**")
        
        if emotions:
            top_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)[:2]
            emotion_text = ", ".join([f"{k} ({v:.2f})" for k, v in top_emotions])
            message_parts.append(f"🎭 Emotions: {emotion_text}")
            
            # Check for detected sub-emotions
            detected_sub_emotion = progression_result.get("detected_sub_emotion", "")
            if detected_sub_emotion and ":" in detected_sub_emotion:
                main_emotion, sub_emotion = detected_sub_emotion.split(":", 1)
                message_parts.append(f"🎯 Specific sub-emotion: {sub_emotion} (within {main_emotion})")
        
        if progression_result.get("primary_mode"):
            message_parts.append(f"🎵 Mode: {progression_result['primary_mode']}")
        
        # Add individual chord insights if available
        individual_available = False
        if isinstance(individual_result, list) and len(individual_result) > 0:
            individual_available = True
        elif isinstance(individual_result, dict) and not individual_result.get("error"):
            individual_available = True
            
        if individual_available:
            message_parts.append("🔍 Individual chord emotions available - ask for details!")
        
        # Add theory context if available
        if theory_result and theory_result.get("style_alternatives"):
            alt_count = len(theory_result["style_alternatives"])
            message_parts.append(f"🎶 {alt_count} style alternatives available")
        
        # Clean chord symbols for better playback
        cleaned_chords = [self._clean_chord_symbol(chord) for chord in chords]
        
        # Include substitution tracking data
        chord_metadata = progression_result.get("chord_metadata", [])
        substitution_count = progression_result.get("substitution_count", 0)
        has_substitutions = progression_result.get("metadata", {}).get("has_substitutions", False)
        generation_method = progression_result.get("generation_method", "unknown")
        
        # Add substitution info to message if neural generation was used
        if generation_method == "neural_generation" and has_substitutions:
            message_parts.append(f"🧠 Neural Network made {substitution_count} creative substitutions")
        elif generation_method == "neural_generation" and not has_substitutions:
            message_parts.append("🧠 Neural Network agreed with database defaults")
        
        # Process voice leading optimization
        voice_leading_data = None
        if chords and emotions:
            # Extract key and style from progression result or use defaults
            key = progression_result.get("key", "C")
            style = progression_result.get("genre", "classical")
            
            voice_leading_data = self._process_voice_leading(chords, emotions, key, style)
            
            # Add voice leading info to message
            if voice_leading_data and not voice_leading_data.get("error"):
                avg_register = voice_leading_data.get("average_register", 4.5)
                voice_cost = voice_leading_data.get("total_voice_leading_cost", 0.0)
                register_range = voice_leading_data.get("register_range", [4, 5])
                
                message_parts.append(f"🎹 Voice Leading: Register {avg_register:.1f} (range {register_range[0]}-{register_range[1]})")
                if len(chords) > 1:
                    avg_movement = voice_cost / (len(chords) - 1)
                    message_parts.append(f"🎵 Smooth transitions: {avg_movement:.1f} semitones average movement")
        
        return {
            "message": "\n\n".join(message_parts),
            "chords": cleaned_chords,
            "original_chords": chords,  # Keep originals for reference
            "chord_metadata": chord_metadata,  # NEW: Substitution tracking
            "substitution_count": substitution_count,  # NEW: Count of substitutions
            "generation_method": generation_method,  # NEW: How chords were generated
            "has_substitutions": has_substitutions,  # NEW: Boolean flag
            "voice_leading": voice_leading_data,  # NEW: Voice leading optimization data
            "emotion": emotions,
            "primary_result": progression_result,
            "alternatives": theory_result.get("style_alternatives", {}),
            "individual_analysis": individual_result,
            "suggestions": self._generate_suggestions(intent, "emotional_progression")
        }
    
    def _synthesize_single_chord(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for individual chord requests"""
        if "individual_results" not in results:
            return {"error": "No individual chord results available"}
            
        individual_results = results["individual_results"]
        
        if not individual_results or len(individual_results) == 0:
            return {"error": "No chord suggestions generated"}
            
        # Get the best chord suggestion
        best_chord = individual_results[0]
        
        # Extract CD information
        cd_value = best_chord.get("consonant_dissonant_value", 0.5)
        cd_description = best_chord.get("consonant_dissonant_description", "moderate")
        cd_preference = intent.extracted_params.get("consonant_dissonant_preference", "not specified")
        
        # Build response message
        chord_symbol = best_chord.get("chord_symbol", "?")
        roman_numeral = best_chord.get("roman_numeral", "?")
        mode_context = best_chord.get("mode_context", "Unknown")
        style_context = best_chord.get("style_context", "Unknown")
        
        # Format emotional content
        emotion_weights = best_chord.get("emotion_weights", {})
        top_emotions = sorted(emotion_weights.items(), key=lambda x: x[1], reverse=True)[:3]
        emotion_text = ", ".join([f"{emotion} ({weight:.2f})" for emotion, weight in top_emotions])
        
        # Create comprehensive response
        response_text = f"🎵 **{chord_symbol}** ({roman_numeral})\n\n"
        response_text += f"🎭 **Emotions**: {emotion_text}\n"
        response_text += f"🎼 **Context**: {mode_context} / {style_context}\n"
        response_text += f"🎶 **Harmonic Character**: {cd_description} (CD: {cd_value:.2f})\n"
        
        if cd_preference != "not specified":
            response_text += f"🎯 **Preference Match**: {cd_preference} harmonic character\n"
        
        # Add alternative suggestions if available
        if len(individual_results) > 1:
            response_text += f"\n🎲 **Alternative chords**:\n"
            for i, alt_chord in enumerate(individual_results[1:4], 2):  # Show up to 3 alternatives
                alt_symbol = alt_chord.get("chord_symbol", "?")
                alt_cd = alt_chord.get("consonant_dissonant_value", 0.5)
                response_text += f"   {i}. {alt_symbol} (CD: {alt_cd:.2f})\n"
        
        return {
            "message": response_text,
            "chord_symbol": chord_symbol,
            "roman_numeral": roman_numeral,
            "emotions": emotion_weights,
            "mode_context": mode_context,
            "style_context": style_context,
            "consonant_dissonant_value": cd_value,
            "consonant_dissonant_description": cd_description,
            "consonant_dissonant_preference": cd_preference,
            "all_chord_options": individual_results,
            "suggestions": self._generate_suggestions(intent, "individual_chord")
        }
    
    def _synthesize_theory_request(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for music theory requests"""
        theory_result = results.get("theory", {})
        progression_result = results.get("progression", {})
        
        message_parts = []
        
        if theory_result.get("progression"):
            chords = theory_result["progression"]
            message_parts.append(f"🎼 **{' → '.join(chords)}**")
        
        style = intent.extracted_params.get("primary_style", "Classical")
        mode = intent.extracted_params.get("primary_mode", "Ionian")
        message_parts.append(f"🎵 Style: {style} | Mode: {mode}")
        
        if theory_result.get("analysis"):
            message_parts.append("🔍 Theoretical analysis available")
        
        if progression_result.get("emotion_weights"):
            emotions = progression_result["emotion_weights"]
            top_emotion = max(emotions.items(), key=lambda x: x[1])
            message_parts.append(f"🎭 Emotional character: {top_emotion[0]} ({top_emotion[1]:.2f})")
        
        # Clean chord symbols for better playback
        raw_chords = theory_result.get("progression", [])
        cleaned_chords = [self._clean_chord_symbol(chord) for chord in raw_chords]
        
        # Process voice leading for theory requests
        voice_leading_data = None
        if raw_chords and progression_result.get("emotion_weights"):
            emotions = progression_result["emotion_weights"]
            key = theory_result.get("key", "C")
            voice_leading_data = self._process_voice_leading(raw_chords, emotions, key, style)
            
            # Add voice leading info to message if available
            if voice_leading_data and not voice_leading_data.get("error"):
                avg_register = voice_leading_data.get("average_register", 4.5)
                voice_cost = voice_leading_data.get("total_voice_leading_cost", 0.0)
                message_parts.append(f"🎹 Voice leading optimized for {style} style (Register: {avg_register:.1f})")
        
        return {
            "message": "\n\n".join(message_parts),
            "chords": cleaned_chords,
            "original_chords": raw_chords,  # Keep originals for reference
            "voice_leading": voice_leading_data,  # NEW: Voice leading data
            "style": style,
            "mode": mode,
            "primary_result": theory_result,
            "emotional_context": progression_result,
            "suggestions": self._generate_suggestions(intent, "theory_request")
        }
    
    def _synthesize_comparison(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for comparison requests"""
        theory_result = results.get("theory", {})
        progression_result = results.get("progression", {})
        
        message_parts = ["🎼 **Style Comparison**"]
        
        # Style characteristics for context
        style_descriptions = {
            "Blues": "Blues progressions emphasize dominant 7ths and bVII chords, creating that characteristic 'blue' sound with tension and release",
            "Jazz": "Jazz uses extended chords (7ths, 9ths) and chromatic movement, often featuring ii-V-I progressions",
            "Classical": "Classical style focuses on functional harmony with clear tonic-dominant relationships and careful voice leading",
            "Pop": "Pop progressions are often simple but catchy, using I-V-vi-IV and similar patterns that are memorable and singable",
            "Rock": "Rock emphasizes power and movement with strong V chords and sometimes augmented tensions for edge",
            "Folk": "Folk music uses simple, modal progressions that feel natural and organic, often staying close to home keys",
            "RnB": "R&B features sophisticated harmony with extended chords and smooth voice leading, creating rich emotional textures",
            "Cinematic": "Cinematic music uses dramatic harmony including diminished chords and unusual extensions for emotional impact"
        }
        
        comparisons = theory_result.get("style_comparison", {})
        if comparisons:
            for style, progression in comparisons.items():
                if progression:
                    # Fix character encoding issue: replace corrupted degree symbols
                    cleaned_progression = []
                    for chord in progression:
                        # Fix the encoding issue with degree symbol
                        cleaned_chord = str(chord).replace('Â°', '°').replace('â°', '°')
                        cleaned_progression.append(cleaned_chord)
                    
                    progression_str = ' → '.join(cleaned_progression)
                    message_parts.append(f"• **{style}**: {progression_str}")
                    
                    # Add style explanation
                    if style in style_descriptions:
                        message_parts.append(f"  *{style_descriptions[style]}*")
        
        # Add emotional context if available
        if progression_result.get("emotion_weights"):
            emotions = progression_result["emotion_weights"]
            top_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)[:2]
            emotion_text = ", ".join([f"{k} ({v:.2f})" for k, v in top_emotions])
            message_parts.append(f"\n🎭 Emotional foundation: {emotion_text}")
        
        # Clean up chord symbols for playback
        cleaned_comparisons = {}
        for style, progression in comparisons.items():
            cleaned_comparisons[style] = [self._clean_chord_symbol(chord) for chord in progression]
        
        return {
            "message": "\n\n".join(message_parts),
            "comparisons": comparisons,
            "style_playback_data": cleaned_comparisons,  # Include cleaned chord data for playback
            "primary_result": theory_result,
            "emotional_context": progression_result,
            "suggestions": self._generate_suggestions(intent, "comparison")
        }
    
    def _synthesize_educational(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for educational requests"""
        theory_result = results.get("theory", {})
        individual_result = results.get("individual", {})
        
        message_parts = ["📚 **Music Theory Explanation**"]
        
        # Add theory explanation if available
        if theory_result.get("explanation"):
            message_parts.append(theory_result["explanation"])
        
        # Add practical examples
        if theory_result.get("examples"):
            message_parts.append("🎵 **Examples:**")
            for example in theory_result["examples"]:
                message_parts.append(f"• {example}")
        
        return {
            "message": "\n\n".join(message_parts),
            "primary_result": theory_result,
            "supporting_data": individual_result,
            "suggestions": self._generate_suggestions(intent, "educational")
        }
    
    def _synthesize_individual_analysis(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize response for individual chord analysis of a progression"""
        individual_results = results.get("individual", [])
        progression = intent.extracted_params.get("context_progression", [])
        
        if not progression:
            return {
                "message": "❌ No progression found in conversation context. Please generate a progression first.",
                "suggestions": ["Generate a new progression", "Ask for a specific chord"]
            }
        
        message_parts = [f"🎼 **Individual Chord Analysis for: {' → '.join(progression)}**"]
        
        # Process each chord analysis
        if isinstance(individual_results, list) and len(individual_results) >= len(progression):
            for i, (chord, analysis) in enumerate(zip(progression, individual_results)):
                message_parts.append(f"\\n**{i+1}. {chord}**")
                
                # Handle errors in analysis
                if analysis.get("error"):
                    message_parts.append(f"  ❌ Error: {analysis['error']}")
                    continue
                
                # Display emotion weights
                if analysis.get("emotion_weights"):
                    emotions = analysis["emotion_weights"]
                    top_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)[:3]
                    emotion_text = ", ".join([f"{k} ({v:.2f})" for k, v in top_emotions if v > 0])
                    if emotion_text:
                        message_parts.append(f"  🎭 Emotions: {emotion_text}")
                    else:
                        message_parts.append(f"  🎭 Neutral emotional content")
                
                # Display harmonic context
                if analysis.get("mode_context") or analysis.get("style_context"):
                    mode = analysis.get("mode_context", "Unknown")
                    style = analysis.get("style_context", "Unknown")
                    message_parts.append(f"  🎼 Context: {mode} ({style})")
                    
                # Display emotional fit score
                if analysis.get("emotional_score") is not None:
                    message_parts.append(f"  🎯 Emotional fit: {analysis['emotional_score']:.2f}")
                
                # Display chord notes if available
                if analysis.get("notes"):
                    message_parts.append(f"  🎵 Notes: {analysis['notes']}")
        else:
            # Fallback if we don't have proper analysis
            message_parts.append("\\n🔍 **Basic chord breakdown:**")
            for i, chord in enumerate(progression):
                message_parts.append(f"\\n**{i+1}. {chord}**")
                message_parts.append(f"  🎵 Roman numeral chord")
                message_parts.append(f"  🎼 Part of progression context")
        
        return {
            "message": "\\n".join(message_parts),
            "chords": progression,
            "individual_analysis": individual_results,
            "progression_breakdown": True,
            "suggestions": [
                "Play this progression",
                "Try in a different style", 
                "Compare with other progressions",
                "Explain the harmonic functions"
            ]
        }
    
    def _synthesize_default(self, intent: UserIntent, results: Dict[str, Any]) -> Dict[str, Any]:
        """Default synthesizer for unrecognized intents"""
        # Fall back to emotional progression
        return self._synthesize_emotional_progression(intent, results)
    
    def _generate_suggestions(self, intent: UserIntent, response_type: str) -> List[str]:
        """Generate contextual follow-up suggestions"""
        base_suggestions = {
            "emotional_progression": [
                "Try this in a different style",
                "Show me individual chord emotions", 
                "Compare across musical styles",
                "Explain the music theory"
            ],
            "individual_chord": [
                "Show me similar chords",
                "Create a progression with this chord",
                "Explain why this chord fits",
                "Try in different modes"
            ],
            "theory_request": [
                "Add emotional context",
                "Compare with other styles",
                "Show me variations",
                "Explain the harmonic functions"
            ],
            "comparison": [
                "Try a different emotion",
                "Add more styles to compare",
                "Explain the differences",
                "Show me individual chord analysis"
            ],
            "educational": [
                "Show me practical examples",
                "Try this concept in practice",
                "Compare with other concepts",
                "Test my understanding"
            ]
        }
        
        suggestions = base_suggestions.get(response_type, base_suggestions["emotional_progression"])
        
        # Customize based on extracted parameters
        if intent.extracted_params.get("styles"):
            suggestions.append("Try other musical styles")
        
        if intent.extracted_params.get("emotions"):
            suggestions.append("Explore different emotions")
        
        return suggestions[:4]  # Limit to 4 suggestions

    def _clean_chord_symbol(self, chord_symbol: str) -> str:
        """Clean up chord symbols for better playback compatibility"""
        if not chord_symbol or not isinstance(chord_symbol, str):
            return "I"  # Safe fallback
        
        # Fix common problematic chord symbols
        cleaned = chord_symbol.strip()
        
        # Convert "alt" chords to specific alterations
        if 'alt' in cleaned:
            # V7alt becomes V7#5 (altered dominant)
            cleaned = cleaned.replace('V7alt', 'V7#5')
            cleaned = cleaned.replace('IValt', 'IV#11')
            cleaned = cleaned.replace('alt', '#5')  # Generic fallback
        
        # Convert complex jazz chords to simpler equivalents for playback
        replacements = {
            'maj7#11': 'M7#11',
            'min7b5': 'ø7',
            'dim7': '°7',
            'aug7': '+7',
            'sus2': 'sus2',
            'sus4': 'sus4',
            '6/9': '6/9',
            'add9': 'add9',
            '13': '7',  # Simplify 13th to 7th for basic playback
            '11': '7',  # Simplify 11th to 7th for basic playback
        }
        
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)
        
        # Remove any remaining unrecognized extensions and keep the core chord
        # This is a safety fallback for complex symbols
        if len(cleaned) > 6 and any(char in cleaned for char in ['b', '#', '/']):
            # For very complex chords, extract the Roman numeral base
            base_match = ""
            for i, char in enumerate(cleaned):
                if char.isalpha() or char in ['i', 'I', 'v', 'V']:
                    base_match += char
                elif char in ['7', '9', 'M', 'm', '+', '°', 'ø', 'sus']:
                    base_match += char
                    break
                else:
                    break
            
            if base_match:
                cleaned = base_match
        
        return cleaned or "I"  # Final safety fallback
        
    def _process_voice_leading(self, chords: List[str], emotions: Dict[str, float], key: str = "C", style: str = "classical") -> Dict[str, Any]:
        """Process voice leading for chord progression"""
        try:
            # Use voice leading engine to optimize voicings
            voice_leading_result = self.voice_leading_engine.optimize_with_style_context(
                chord_progression=chords,
                emotion_weights=emotions,
                key=key,
                style_context=style.lower()
            )
            
            # Extract voice leading data
            voice_leading_data = {
                "voiced_chords": [],
                "register_analysis": voice_leading_result.register_analysis,
                "total_voice_leading_cost": voice_leading_result.total_voice_leading_cost,
                "harmonic_rhythm": voice_leading_result.harmonic_rhythm,
                "average_register": voice_leading_result.register_analysis.get("average_register", 4.5),
                "register_range": [
                    min(vc.register_range[0] for vc in voice_leading_result.voiced_chords),
                    max(vc.register_range[1] for vc in voice_leading_result.voiced_chords)
                ] if voice_leading_result.voiced_chords else [4, 5]
            }
            
            # Process each voiced chord
            for voiced_chord in voice_leading_result.voiced_chords:
                chord_data = {
                    "chord_symbol": voiced_chord.chord_symbol,
                    "notes": voiced_chord.notes,
                    "register_range": voiced_chord.register_range,
                    "voice_leading_cost": voiced_chord.voice_leading_cost,
                    "emotional_fitness": voiced_chord.emotional_fitness,
                    "notes_display": " - ".join([f"{note}{octave}" for note, octave in voiced_chord.notes])
                }
                voice_leading_data["voiced_chords"].append(chord_data)
            
            return voice_leading_data
            
        except Exception as e:
            print(f"Voice leading processing error: {e}")
            # Return fallback data
            return {
                "voiced_chords": [{"chord_symbol": chord, "notes": [], "register_range": [4, 5], "voice_leading_cost": 0.0, "emotional_fitness": 0.5, "notes_display": "Fallback mode"} for chord in chords],
                "register_analysis": {"target_registers": [4, 5], "average_register": 4.5},
                "total_voice_leading_cost": 0.0,
                "harmonic_rhythm": {"tensions": [0.5] * len(chords), "durations": [1.0] * len(chords)},
                "average_register": 4.5,
                "register_range": [4, 5],
                "error": str(e)
            }

class PersistentChatLog:
    """Manages persistent chat logs stored in a JSON file."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        # Ensure the file exists
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w') as f:
                json.dump({}, f)

    def load_chatlog(self) -> Dict[str, Any]:
        """Load chat log from the JSON file."""
        with open(self.file_path, 'r') as f:
            return json.load(f)

    def save_chatlog(self, session_id: str, context: ConversationContext):
        """Save context to the chat log."""
        if not context:
            return  # Don't save if context is None
            
        chatlog = self.load_chatlog()
        chatlog[session_id] = {
            "last_response": context.last_response,
            "last_progression": context.last_progression,
            "last_emotion": context.last_emotion,
            "last_style": context.last_style,
            "last_mode": context.last_mode,
            "timestamp": context.timestamp
        }
        with open(self.file_path, 'w') as f:
            json.dump(chatlog, f, indent=4)

    def get_context(self, session_id: str) -> Optional[ConversationContext]:
        """Retrieve context from the chat log."""
        chatlog = self.load_chatlog()
        session_data = chatlog.get(session_id)
        if session_data:
            return ConversationContext(
                last_response=session_data["last_response"],
                last_progression=session_data["last_progression"],
                last_emotion=session_data["last_emotion"],
                last_style=session_data["last_style"],
                last_mode=session_data["last_mode"],
                session_id=session_id,
                timestamp=session_data["timestamp"]
            )
        return None

# Initialize PersistentChatLog
persistent_chatlog = PersistentChatLog("persistent_chatlog.json")

# Initialize ConversationMemory
conversation_memory = ConversationMemory()

class IntegratedMusicChatServer:
    """Main server class that coordinates all three models"""
    
    def __init__(self):
        print("Initializing Integrated Music Chat Server...")
        
        # Initialize models
        print("Loading Chord Progression Model...")
        self.progression_model = ChordProgressionModel()
        
        print("Loading Individual Chord Model...")
        self.individual_model = IndividualChordModel()
        
        print("Loading Enhanced Solfege Theory Engine...")
        self.theory_engine = EnhancedSolfegeTheoryEngine()
        
        print("Loading Voice Leading Engine...")
        self.voice_leading_engine = EnhancedVoiceLeadingEngine()
        
        # Initialize support systems
        self.intent_classifier = IntentClassifier()
        self.response_synthesizer = ResponseSynthesizer()
        self.conversation_memory = ConversationMemory()
        
        print("✓ All models loaded successfully!")
    
    def process_message(self, user_input: str, context: ConversationContext = None, session_id: str = None) -> Dict[str, Any]:
        """Process a user message and return integrated response with conversation context"""
        try:
            # Use provided context or get from memory
            conversation_context = context
            if not conversation_context and session_id:
                conversation_context = self.conversation_memory.get_context(session_id)
            
            # Classify intent with context
            intent = self.intent_classifier.classify(user_input, conversation_context)
            
            # Route to appropriate models
            model_results = {}
            
            # For individual analysis, we might need to analyze each chord in the progression
            if intent.primary_intent == "individual_analysis" and conversation_context and conversation_context.last_progression:
                progression = conversation_context.last_progression
                context_emotion = conversation_context.last_emotion or ""
                
                if progression:
                    # Determine the correct mode for this progression using theory engine
                    progression_mode = self._determine_progression_mode(progression, context_emotion)
                    print(f"DEBUG: Determined progression mode: {progression_mode} for {progression}")
                    
                    # Generate individual chord analysis for each chord in the progression
                    individual_analyses = []
                    for chord in progression:
                        try:
                            # Validate chord legality in the determined mode
                            is_valid = self._validate_chord_in_mode(chord, progression_mode)
                            
                            if is_valid:
                                # Create a more specific prompt that includes proper context
                                if context_emotion:
                                    emotion_prompt = f"{context_emotion} {chord} chord in {progression_mode} mode"
                                else:
                                    emotion_prompt = f"{chord} chord in {progression_mode} mode"
                                    
                                chord_analysis = self.individual_model.generate_chord_from_prompt(emotion_prompt)
                                
                                # Ensure the analysis has the correct mode context
                                if isinstance(chord_analysis, list) and len(chord_analysis) > 0:
                                    analysis = chord_analysis[0].copy()
                                    analysis["mode_context"] = progression_mode
                                    analysis["theory_validated"] = True
                                    individual_analyses.append(analysis)
                                elif isinstance(chord_analysis, dict):
                                    analysis = chord_analysis.copy()
                                    analysis["mode_context"] = progression_mode
                                    analysis["theory_validated"] = True
                                    individual_analyses.append(analysis)
                                else:
                                    # Create theory-based fallback analysis
                                    individual_analyses.append({
                                        "chord_symbol": chord,
                                        "roman_numeral": chord,
                                        "mode_context": progression_mode,
                                        "style_context": "Classical",
                                        "emotion_weights": self._get_chord_emotions_by_theory(chord, progression_mode),
                                        "emotional_score": 0.5,
                                        "theory_validated": True
                                    })
                            else:
                                # Chord is invalid in this mode - report the theory violation
                                individual_analyses.append({
                                    "chord_symbol": chord,
                                    "roman_numeral": chord,
                                    "mode_context": progression_mode,
                                    "style_context": "Invalid",
                                    "error": f"Theory violation: {chord} is not valid in {progression_mode} mode",
                                    "emotion_weights": {},
                                    "emotional_score": 0.0,
                                    "theory_validated": False
                                })
                                
                        except Exception as e:
                            print(f"Error analyzing chord {chord}: {e}")
                            individual_analyses.append({
                                "chord_symbol": chord,
                                "roman_numeral": chord,
                                "mode_context": progression_mode,
                                "style_context": "Error",
                                "error": str(e),
                                "emotion_weights": {},
                                "emotional_score": 0.0,
                                "theory_validated": False
                            })
                    
                    model_results["individual"] = individual_analyses
            elif "progression" in intent.suggested_models:
                model_results["progression"] = self._call_progression_model(user_input, intent)
            
            if "individual" in intent.suggested_models and intent.primary_intent != "individual_analysis":
                model_results["individual"] = self._call_individual_model(user_input, intent)
            
            if "theory" in intent.suggested_models:
                model_results["theory"] = self._call_theory_engine(user_input, intent)
            
            # Synthesize unified response
            response = self.response_synthesizer.synthesize(intent, model_results)
            
            # Add metadata
            response.update({
                "intent": intent.primary_intent,
                "confidence": intent.confidence,
                "models_used": intent.suggested_models,
                "timestamp": time.time()
            })
            
            # Store conversation context for follow-up requests
            if session_id:
                self.conversation_memory.store_context(session_id, response)
            
            return response
            
        except Exception as e:
            return {
                "error": str(e),
                "message": "I encountered an error processing your request. Please try again.",
                "timestamp": time.time()
            }
    
    def _call_progression_model(self, user_input: str, intent: UserIntent) -> Dict[str, Any]:
        """Call the chord progression model"""
        try:
            # Use primary emotion or default to the input text
            emotion_text = intent.extracted_params.get("primary_emotion", user_input)
            style_preference = intent.extracted_params.get("primary_style", "Pop")
            
            results = self.progression_model.generate_from_prompt(
                emotion_text, 
                genre_preference=style_preference, 
                num_progressions=1
            )
            
            if results:
                return results[0]
            else:
                return {"error": "No progression generated"}
                
        except Exception as e:
            return {"error": f"Progression model error: {str(e)}"}
    
    def _call_individual_model(self, user_input: str, intent: UserIntent) -> Dict[str, Any]:
        """Call the individual chord model"""
        try:
            # Extract consonant/dissonant preference from intent
            consonant_dissonant_preference = intent.extracted_params.get("consonant_dissonant_preference")
            
            # Convert string preferences to numerical values
            if consonant_dissonant_preference == "consonant":
                consonant_dissonant_preference = 0.2
            elif consonant_dissonant_preference == "dissonant":
                consonant_dissonant_preference = 0.8
            elif consonant_dissonant_preference == "moderate":
                consonant_dissonant_preference = 0.5
            
            num_options = intent.extracted_params.get("num_options", 3)
            mode_preference = intent.extracted_params.get("mode_preference")
            style_preference = intent.extracted_params.get("style_preference")
            
            results = self.individual_model.generate_chord_from_prompt(
                user_input,
                num_options=num_options,
                mode_preference=mode_preference,
                style_preference=style_preference,
                consonant_dissonant_preference=consonant_dissonant_preference
            )
            
            return {"individual_results": results}
        except Exception as e:
            return {"error": f"Individual model error: {str(e)}"}
    
    def _call_theory_engine(self, user_input: str, intent: UserIntent) -> Dict[str, Any]:
        """Call the enhanced solfege theory engine"""
        try:
            style = intent.extracted_params.get("primary_style", "Classical")
            mode = intent.extracted_params.get("primary_mode", "Ionian")
            length = intent.extracted_params.get("length", 4)
            
            if intent.primary_intent == "comparison":
                # Generate style comparison
                comparison = self.theory_engine.compare_style_progressions(mode, length)
                return {"style_comparison": comparison}
            
            elif intent.primary_intent == "theory_request":
                # Generate specific style progression
                progression = self.theory_engine.generate_legal_progression(style, mode, length)
                return {"progression": progression, "style": style, "mode": mode}
            
            else:
                # Generate style alternatives for emotion
                emotion = intent.extracted_params.get("primary_emotion", "happy")
                comparison = self.theory_engine.compare_style_progressions(mode, length)
                return {"style_alternatives": comparison}
                
        except Exception as e:
            return {"error": f"Theory engine error: {str(e)}"}
    
    def _determine_progression_mode(self, progression: List[str], context_emotion: str = "") -> str:
        """Determine the correct mode for a progression using theory engine validation"""
        if not progression:
            return "Unknown"
        
        try:
            # Rule-based mode determination from chord patterns
            has_minor_root = any(chord.startswith('i') and not chord.startswith('ii') for chord in progression)
            has_major_root = any(chord.startswith('I') and not chord.startswith('II') for chord in progression)
            has_minor_iv = 'iv' in progression
            has_major_IV = 'IV' in progression
            
            # Determine most likely mode
            if has_minor_root and has_minor_iv:
                candidate_mode = "Aeolian"  # Natural minor
            elif has_major_root and has_major_IV and not has_minor_iv:
                candidate_mode = "Ionian"   # Major
            elif has_minor_root and any(chord in progression for chord in ["♭II", "♭VII"]):
                candidate_mode = "Phrygian"  # Minor with flat intervals
            else:
                # Try to infer from emotion if available
                if context_emotion:
                    emotion_mode_map = {
                        "Joy": "Ionian", "Sadness": "Aeolian", "Fear": "Phrygian",
                        "Anger": "Phrygian", "Love": "Mixolydian", "Trust": "Dorian",
                        "Malice": "Locrian", "Wonder": "Lydian", "Empowerment": "Ionian",
                        "Gratitude": "Ionian", "Reverence": "Lydian", "Transcendence": "Lydian"
                    }
                    candidate_mode = emotion_mode_map.get(context_emotion, "Ionian")
                else:
                    candidate_mode = "Ionian"  # Default fallback
            
            # Validate with theory engine
            try:
                analysis = self.theory_engine.analyze_progression(progression, candidate_mode)
                if analysis and not analysis.get("error"):
                    return candidate_mode
            except:
                pass
            
            # If validation fails, try common alternatives
            alternatives = ["Aeolian", "Ionian", "Dorian", "Phrygian"]
            for alt_mode in alternatives:
                if alt_mode != candidate_mode:
                    try:
                        alt_analysis = self.theory_engine.analyze_progression(progression, alt_mode)
                        if alt_analysis and not alt_analysis.get("error"):
                            return alt_mode
                    except:
                        continue
            
            # If all validations fail, return the best guess anyway
            return candidate_mode
                
        except Exception as e:
            print(f"Error determining progression mode: {e}")
            # Fallback logic without theory engine
            if any(chord.startswith('i') for chord in progression):
                return "Aeolian"
            else:
                return "Ionian"

    def _validate_chord_in_mode(self, chord: str, mode: str) -> bool:
        """Validate if a chord is legal in the given mode"""
        try:
            # Use theory engine to validate
            test_progression = [chord]
            analysis = self.theory_engine.analyze_progression(test_progression, mode)
            return analysis and not analysis.get("error")
        except:
            # Fallback validation rules
            mode_chord_patterns = {
                "Ionian": ["I", "ii", "iii", "IV", "V", "vi", "vii°"],
                "Aeolian": ["i", "ii°", "♭III", "iv", "v", "♭VI", "♭VII"],
                "Dorian": ["i", "ii", "♭III", "IV", "v", "vi°", "♭VII"],
                "Phrygian": ["i", "♭II", "♭III", "iv", "v°", "♭VI", "♭vii"],
                "Mixolydian": ["I", "ii", "iii°", "IV", "v", "vi", "♭VII"],
                "Lydian": ["I", "II", "iii", "♯iv°", "V", "vi", "vii"],
                "Locrian": ["i°", "♭II", "♭iii", "iv", "♭V", "♭VI", "♭vii"]
            }
            
            valid_chords = mode_chord_patterns.get(mode, [])
            return chord in valid_chords or any(chord.startswith(base) for base in valid_chords)

    def _get_chord_emotions_by_theory(self, chord: str, mode: str) -> Dict[str, float]:
        """Get emotion weights for a chord based on music theory rules"""
        emotion_weights = {
            "Joy": 0.0, "Sadness": 0.0, "Fear": 0.0, "Anger": 0.0,
            "Disgust": 0.0, "Surprise": 0.0, "Trust": 0.0, "Anticipation": 0.0,
            "Shame": 0.0, "Love": 0.0, "Envy": 0.0, "Aesthetic Awe": 0.0,
            "Malice": 0.0, "Arousal": 0.0, "Guilt": 0.0, "Reverence": 0.0,
            "Wonder": 0.0, "Dissociation": 0.0, "Empowerment": 0.0, 
            "Belonging": 0.0, "Ideology": 0.0, "Gratitude": 0.0, "Transcendence": 0.0
        }
        
        # Minor chords generally evoke sadness
        if chord.startswith('i') and not chord.startswith('ii'):  # i, iv, v (minor)
            emotion_weights["Sadness"] = 0.8
            emotion_weights["Shame"] = 0.3
            emotion_weights["Fear"] = 0.2
        elif chord in ['iv', 'v']:  # minor iv, v
            emotion_weights["Sadness"] = 0.7
            emotion_weights["Trust"] = 0.3
        
        # Major chords generally evoke joy
        elif chord.startswith('I') and not chord.startswith('II'):  # I, IV, V (major)
            emotion_weights["Joy"] = 0.9
            emotion_weights["Trust"] = 0.6
            emotion_weights["Love"] = 0.4
        elif chord in ['IV', 'V']:  # Major IV, V
            emotion_weights["Joy"] = 0.8
            emotion_weights["Anticipation"] = 0.5
            
        # Diminished chords evoke tension/fear
        elif '°' in chord or 'dim' in chord:
            emotion_weights["Fear"] = 0.8
            emotion_weights["Surprise"] = 0.5
            emotion_weights["Disgust"] = 0.3
            
        # Flat intervals (borrowed from other modes) add complexity
        elif '♭' in chord:
            if mode in ["Aeolian", "Phrygian"]:
                emotion_weights["Sadness"] = 0.6
                emotion_weights["Anger"] = 0.4
            else:
                emotion_weights["Surprise"] = 0.7
                emotion_weights["Aesthetic Awe"] = 0.5
        
        return emotion_weights
    
if __name__ == "__main__":
    # Initialize the integrated server
    integrated_server = IntegratedMusicChatServer()
    
    # Test endpoint for basic functionality
    app = Flask(__name__)
    app.secret_key = 'music_theory_chat_secret_key_2024'
    CORS(app, supports_credentials=True)
    
    @app.route('/')
    def serve_chat_interface():
        """Serve the main chat interface"""
        return send_from_directory('.', 'chord_chat.html')
    
    @app.route('/health')
    def health_check():
        """Health check endpoint"""
        return jsonify({"status": "healthy", "models": ["progression", "individual", "theory"]})
    
    @app.route('/chat/integrated', methods=['POST'])
    def integrated_chat():
        """Main integrated chat endpoint"""
        try:
            data = request.get_json()
            user_message = data.get('message', '')
            client_context = data.get('context', {})  # Client-side context (chatlog)
            session_id = session.get('session_id')

            if not session_id:
                session_id = f"session_{int(time.time())}_{random.randint(1000, 9999)}"
                session['session_id'] = session_id

            # Build unified context from multiple sources
            context = None
            
            # First try server-side persistent context
            context = persistent_chatlog.get_context(session_id)
            
            # Fall back to in-memory context
            if not context:
                context = integrated_server.conversation_memory.get_context(session_id)
            
            # Fall back to client context if we have useful data
            if not context and client_context.get('lastProgression'):
                context = ConversationContext(
                    last_response=client_context.get('lastResponse', {}),
                    last_progression=client_context.get('lastProgression', []),
                    last_emotion=client_context.get('lastEmotion', ''),
                    last_style=client_context.get('lastStyle', ''),
                    last_mode=client_context.get('lastMode', ''),
                    session_id=session_id,
                    timestamp=time.time()
                )
            
            # Final fallback - create new context
            if not context:
                context = ConversationContext(
                    last_response={},
                    last_progression=[],
                    last_emotion="",
                    last_style="",
                    last_mode="",
                    session_id=session_id,
                    timestamp=time.time()
                )

            # Process the message
            response = integrated_server.process_message(user_message, context, session_id)

            # Extract conversation data from response for context
            response_context = {
                'chords': response.get('chords', []),
                'primary_emotion': None,
                'primary_style': response.get('primary_result', {}).get('genre', ''),
                'primary_mode': response.get('primary_result', {}).get('primary_mode', '')
            }
            
            # Get primary emotion from response
            emotions = response.get('emotions', {})
            if emotions:
                response_context['primary_emotion'] = max(emotions.items(), key=lambda x: x[1])[0]

            # Store updated context in both systems
            integrated_server.conversation_memory.store_context(session_id, response)
            
            # Update persistent context with extracted data
            updated_context = integrated_server.conversation_memory.get_context(session_id)
            if updated_context:
                # Enhance context with extracted conversation data
                updated_context.last_progression = response_context['chords']
                updated_context.last_emotion = response_context['primary_emotion'] or updated_context.last_emotion
                updated_context.last_style = response_context['primary_style'] or updated_context.last_style
                updated_context.last_mode = response_context['primary_mode'] or updated_context.last_mode
                updated_context.timestamp = time.time()
                
                persistent_chatlog.save_chatlog(session_id, updated_context)

            return jsonify(response)

        except Exception as e:
            print(f"Error in /chat/integrated endpoint: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Processing error: {str(e)}"}), 500
    
    @app.route('/chat/analyze', methods=['POST'])
    def analyze_progression():
        """Analyze a chord progression"""
        try:
            data = request.get_json()
            chords = data.get('chords', [])
            
            if not chords:
                return jsonify({"error": "No chords provided"}), 400
            
            # Use theory engine to analyze
            try:
                result = integrated_server.theory_engine.analyze_progression(chords, "Ionian")
                return jsonify({"analysis": result, "chords": chords})
            except Exception as e:
                return jsonify({"error": f"Analysis failed: {str(e)}"}), 500
                
        except Exception as e:
            return jsonify({"error": f"Request error: {str(e)}"}), 500
    
    @app.route('/debug/context', methods=['GET'])
    def debug_context():
        """Debug endpoint to check conversation context"""
        try:
            session_id = session.get('session_id')
            if not session_id:
                return jsonify({"error": "No session ID found"})
            
            # Get context from all sources
            persistent_context = persistent_chatlog.get_context(session_id)
            memory_context = integrated_server.conversation_memory.get_context(session_id)
            
            context_info = {
                "session_id": session_id,
                "persistent_context": {
                    "exists": persistent_context is not None,
                    "last_progression": persistent_context.last_progression if persistent_context else None,
                    "last_emotion": persistent_context.last_emotion if persistent_context else None,
                    "last_mode": persistent_context.last_mode if persistent_context else None,
                    "timestamp": persistent_context.timestamp if persistent_context else None
                },
                "memory_context": {
                    "exists": memory_context is not None,
                    "last_progression": memory_context.last_progression if memory_context else None,
                    "last_emotion": memory_context.last_emotion if memory_context else None,
                    "last_mode": memory_context.last_mode if memory_context else None,
                    "timestamp": memory_context.timestamp if memory_context else None
                },
                "all_sessions": list(integrated_server.conversation_memory.sessions.keys())
            }
            
            return jsonify(context_info)
            
        except Exception as e:
            return jsonify({"error": f"Debug error: {str(e)}"}), 500
    
    @app.route('/chord/generate', methods=['POST'])
    def generate_chord():
        """Generate individual chords with consonant/dissonant preferences"""
        try:
            data = request.get_json()
            emotion_prompt = data.get('emotion_prompt', '')
            num_options = data.get('num_options', 3)
            consonant_dissonant_preference = data.get('consonant_dissonant_preference')
            mode_preference = data.get('mode_preference')
            style_preference = data.get('style_preference')
            
            if not emotion_prompt:
                return jsonify({"error": "No emotion prompt provided"}), 400
            
            # Generate chords using individual model
            results = integrated_server.individual_model.generate_chord_from_prompt(
                emotion_prompt,
                num_options=num_options,
                consonant_dissonant_preference=consonant_dissonant_preference,
                mode_preference=mode_preference,
                style_preference=style_preference
            )
            
            return jsonify({
                "results": results,
                "query": emotion_prompt,
                "parameters": {
                    "num_options": num_options,
                    "consonant_dissonant_preference": consonant_dissonant_preference,
                    "mode_preference": mode_preference,
                    "style_preference": style_preference
                }
            })
            
        except Exception as e:
            return jsonify({"error": f"Chord generation error: {str(e)}"}), 500

    @app.route('/progression/analyze', methods=['POST'])
    def analyze_progression_cd():
        """Analyze a progression with consonant/dissonant features"""
        try:
            data = request.get_json()
            chords = data.get('chords', [])
            
            if not chords:
                return jsonify({"error": "No chords provided"}), 400
            
            # Use integrated server to analyze progression
            analysis = integrated_server.analyze_progression_context(chords)
            
            return jsonify({
                "analysis": analysis,
                "chords": chords,
                "cd_features": {
                    "average_consonant_dissonant": analysis.get('average_consonant_dissonant', 0.5),
                    "cd_flow_description": analysis.get('cd_flow_description', 'No description available'),
                    "consonant_dissonant_trajectory": analysis.get('consonant_dissonant_trajectory', [])
                }
            })
            
        except Exception as e:
            return jsonify({"error": f"Progression analysis error: {str(e)}"}), 500
    
    print("✓ All models loaded successfully!")
    print("🎼 Integrated Music Chat Server is ready!")
    print("\nAvailable endpoints:")
    print("  GET  /              - Chat interface")
    print("  GET  /health        - Health check") 
    print("  POST /chat/integrated - Integrated chat")
    print("  POST /chat/analyze   - Progression analysis")
    print("  GET  /debug/context  - Debug conversation context")
    print("  POST /chord/generate - Generate individual chords with preferences")
    print("  POST /progression/analyze - Analyze a progression with consonant/dissonant features")
    print()
    
    # Run the server
    app.run(host='0.0.0.0', port=5004, debug=True)
