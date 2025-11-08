import React, { useEffect, useMemo, useRef, useState } from 'react'

// Use environment variable for API URL, fallback to localhost for development
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:3002'

export default function App() {
const sessionId = useMemo(()=> `sess-${Date.now()}`,[])
const [messages, setMessages] = useState<Array<{role:string, content:string, quiz?:any, quizId?:string}>>([])
const [draft, setDraft] = useState('')
const [loading, setLoading] = useState(false)
const accRef = useRef<HTMLDivElement>(null)
const [activeQuiz, setActiveQuiz] = useState<{type:string, data?:any, result?:any} | null>(null)
const [shuffledEnglish, setShuffledEnglish] = useState<string[]>([])
const [isRecording, setIsRecording] = useState(false)
const mediaRecorderRef = useRef<MediaRecorder | null>(null)
const audioChunksRef = useRef<Blob[]>([])
// Icon fallback state (currently using direct fallback in onError)
// const [showIconFallback, setShowIconFallback] = useState(false)

// Helper function to detect image type from base64
function getImageDataUrl(base64: string): string {
  // Try to decode and check if it's SVG (starts with <svg)
  try {
    const decoded = atob(base64.substring(0, 100)) // Decode first 100 chars
    if (decoded.trim().startsWith('<svg') || decoded.trim().startsWith('<?xml')) {
      return `data:image/svg+xml;base64,${base64}`
    }
  } catch (e) {
    // If decoding fails, assume it's binary (PNG/JPG)
  }
  // Default to PNG for binary images
  return `data:image/png;base64,${base64}`
}


useEffect(()=>{ accRef.current?.scrollTo({top:999999, behavior:'smooth'}) }, [messages, loading])

// Auto-start conversation on mount
const hasStartedRef = useRef(false)
const waitingForQuizCompletion = useRef(false)
useEffect(()=>{
if(!hasStartedRef.current && messages.length === 0){
hasStartedRef.current = true
send('hi')
}
}, [messages.length])




async function send(text: string){
// Allow empty string for quiz completion trigger
// Allow empty messages if waiting for quiz completion OR if we're explicitly continuing after quiz
if(!text.trim() && !waitingForQuizCompletion.current) return
if(text.trim()) {
setMessages(m=>[...m, { role:'user', content: text }])
}
setDraft('')
setLoading(true)

try {
const res = await fetch(`${API_BASE}/api/chat`,{
method:'POST', headers:{'Content-Type':'application/json'},
body: JSON.stringify({ sessionId, message: text })
})

if(!res.ok) {
throw new Error(`HTTP ${res.status}: ${res.statusText}`)
}

if(!res.body) {
throw new Error('No response body')
}

const reader = res.body.getReader()
let assistant = ''
let assistantMsgAdded = false
while(true){
const { value, done } = await reader.read()
if(done) break
const chunkStr = new TextDecoder().decode(value)
for(const line of chunkStr.split('\n')){
if(!line.trim() || !line.startsWith('data:')) continue
try {
const payload = JSON.parse(line.replace('data:','').trim())
if(payload.error){
throw new Error(payload.error)
}
if(payload.test_type){
console.log('[Frontend] ⚡ Test type received:', payload.test_type)
waitingForQuizCompletion.current = true
// Add quiz placeholder to messages immediately
const quizId = `quiz-${Date.now()}`
setMessages(m=>[...m, { 
  role: 'quiz', 
  content: '', 
  quiz: { type: payload.test_type, id: quizId, status: 'loading' }
}])
// Clear any existing active quiz state
setActiveQuiz(null)
// Small delay to ensure state is cleared, then generate quiz
setTimeout(() => {
  console.log(`[Frontend] 📝 Generating ${payload.test_type} quiz (ID: ${quizId})...`)
  // Trigger quiz generation IMMEDIATELY
  if(payload.test_type === 'unit_completion'){
    generateUnitCompletionQuiz(quizId)
  } else if(payload.test_type === 'keyword_match'){
    generateKeywordMatchQuiz(quizId)
  } else if(payload.test_type === 'image_detection'){
    generateImageDetectionQuiz(quizId)
  } else if(payload.test_type === 'podcast'){
    generatePodcastQuiz(quizId)
  } else if(payload.test_type === 'pronunciation'){
    generatePronunciationQuiz(quizId)
  } else if(payload.test_type === 'reading'){
    generateReadingQuiz(quizId)
  }
}, 100)
}
if(payload.chunk){ 
assistant += payload.chunk
if(!assistantMsgAdded) {
setMessages(m=>[...m, { role:'assistant', content: assistant }])
assistantMsgAdded = true
} else {
setMessages(m=>[...m.slice(0, -1), { role:'assistant', content: assistant }])
}
}
if(payload.done){
if(!assistantMsgAdded) {
setMessages(m=>[...m, { role:'assistant', content: assistant }])
}
assistant = ''
assistantMsgAdded = false
}
} catch(e: any) {
if(e.message !== 'Unexpected end of JSON input') {
console.error('Parse error:', e)
}
}
}
}
} catch(e: any) {
console.error('Send error:', e)
setMessages(m=>[...m, { role:'assistant', content: `Error: ${e.message}` }])
} finally { 
setLoading(false) 
}
}

async function generateUnitCompletionQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling unit_completion generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/unit-completion/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Unit completion quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
// Update the quiz message in messages array
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'unit_completion', status: 'ready', data: { ...data.quiz, masked_word: data.masked_word } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'unit_completion',
data: {
...data.quiz,
masked_word: data.masked_word,
quizId
}
})
console.log(`[Frontend] ✅ Unit completion quiz ready (Quiz ID: ${quizId})`)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function generateKeywordMatchQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling keyword_match generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/keyword-match/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Keyword match quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
const englishWords = data.quiz.pairs.map((p: any) => p.english).sort(() => Math.random() - 0.5)
setShuffledEnglish(englishWords)
// Update quiz in messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'keyword_match', status: 'ready', data: { pairs: data.quiz.pairs, matches: [] } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'keyword_match',
data: {
pairs: data.quiz.pairs,
matches: [],
quizId
}
})
console.log(`[Frontend] ✅ Keyword match quiz ready (Quiz ID: ${quizId})`)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function submitKeywordMatch(){
if(!activeQuiz?.data || activeQuiz.type !== 'keyword_match' || !activeQuiz.data.quizId) return
if(!activeQuiz.data.matches || activeQuiz.data.matches.length !== 5) return  // Need all 5 matches

const quizId = activeQuiz.data.quizId
try {
const res = await fetch(`${API_BASE}/api/quiz/keyword-match/validate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({
sessionId,
matches: activeQuiz.data.matches
})
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { all_correct: data.all_correct, score: data.score, results: data.results, total: data.total, correct_count: data.correct_count } } }
    : msg
))
// Update activeQuiz for display
setActiveQuiz({
...activeQuiz,
result: {
all_correct: data.all_correct,
score: data.score,
results: data.results,
total: data.total,
correct_count: data.correct_count
}
})
// Always auto-continue after result is shown (both correct and incorrect)
// Capture result status to avoid stale closure reference
const allCorrect = data.all_correct
const autoProgressDelay = allCorrect ? 2000 : 5000

setTimeout(()=>{
setActiveQuiz(null)
waitingForQuizCompletion.current = true  // Set flag before sending empty message
send('')  // Empty message triggers agent to provide feedback and start next quiz
waitingForQuizCompletion.current = false  // Reset after sending
}, autoProgressDelay)
}
} catch(e: any){
console.error('Validation error:', e)
}
}

function handleKeywordDragStart(e: React.DragEvent, word: string, type: 'english' | 'spanish'){
e.dataTransfer.setData('text/plain', JSON.stringify({word, type}))
}

function handleKeywordDragOver(e: React.DragEvent){
e.preventDefault()
}

function handleKeywordDrop(e: React.DragEvent, targetSpanish: string){
e.preventDefault()
const data = JSON.parse(e.dataTransfer.getData('text/plain'))
if(!activeQuiz || activeQuiz.type !== 'keyword_match') return

// Only allow dropping English words onto target language words
if(data.type === 'english'){
const englishWord = data.word
// Check if this target language word already has a match
const existingMatchIndex = activeQuiz.data.matches.findIndex((m: any) => m.spanish === targetSpanish)
const matches = [...(activeQuiz.data.matches || [])]
if(existingMatchIndex >= 0){
matches[existingMatchIndex] = {spanish: targetSpanish, english: englishWord}
} else {
matches.push({spanish: targetSpanish, english: englishWord})
}
// Update matches (don't auto-submit, let user verify)
setActiveQuiz({
...activeQuiz,
data: {
...activeQuiz.data,
matches
}
})
}
}

async function generateImageDetectionQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling image_detection generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/image-detection/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Image detection quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
// Update quiz in messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'image_detection', status: 'ready', data: { object_word: data.quiz.object_word, image_url: data.quiz.image_url, image_base64: data.quiz.image_base64 } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'image_detection',
data: {
object_word: data.quiz.object_word,
image_url: data.quiz.image_url,
image_base64: data.quiz.image_base64,
quizId
}
})
console.log(`[Frontend] ✅ Image detection quiz ready (Quiz ID: ${quizId})`)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function submitImageDetectionAnswer(answer: string){
if(!activeQuiz?.data || activeQuiz.type !== 'image_detection' || !activeQuiz.data.quizId) return
const correctWord = activeQuiz.data.object_word
const quizId = activeQuiz.data.quizId
try {
const res = await fetch(`${API_BASE}/api/quiz/image-detection/validate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({
sessionId,
userAnswer: answer,
correctWord
})
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { correct: data.correct, score: data.score, feedback: data.feedback, correct_answer: data.correct_answer, user_answer: answer } } }
    : msg
))
// Update activeQuiz for display
setActiveQuiz({
...activeQuiz,
result: {
correct: data.correct,
score: data.score,
feedback: data.feedback,
correct_answer: data.correct_answer,
user_answer: answer
}
})
// Always auto-continue (both correct and incorrect) - show result for 2 seconds then continue
setTimeout(()=>{
  setActiveQuiz(null)
  waitingForQuizCompletion.current = true  // Set flag before sending empty message
  send('')  // Empty message triggers agent to provide feedback and start next quiz
  waitingForQuizCompletion.current = false  // Reset after sending
}, 2000)
}
} catch(e: any){
console.error('Validation error:', e)
}
}

async function generatePodcastQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling podcast generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/podcast/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Podcast quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
// Update quiz in messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'podcast', status: 'ready', data: { conversation: data.quiz.conversation, question: data.quiz.question, correct_answer: data.correct_answer, showQuestion: false, audio_base64: data.quiz.audio_base64 } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'podcast',
data: {
conversation: data.quiz.conversation,
question: data.quiz.question,
correct_answer: data.correct_answer,
showQuestion: false,
audio_base64: data.quiz.audio_base64,
quizId
}
})
console.log(`[Frontend] ✅ Podcast quiz ready (Quiz ID: ${quizId})`)
// After 3 seconds, show the question
setTimeout(()=>{
setActiveQuiz((prev: any) => prev ? {
...prev,
data: {
...prev.data,
showQuestion: true
}
} : null)
// Also update messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, data: { ...msg.quiz.data, showQuestion: true } } }
    : msg
))
}, 3000)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function generatePronunciationQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling pronunciation generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/pronunciation/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Pronunciation quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
// Update quiz in messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'pronunciation', status: 'ready', data: { sentence: data.quiz.sentence } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'pronunciation',
data: {
sentence: data.quiz.sentence,
quizId
}
})
console.log(`[Frontend] ✅ Pronunciation quiz ready (Quiz ID: ${quizId})`)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function startRecording(){
try {
const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
const mediaRecorder = new MediaRecorder(stream, {
mimeType: 'audio/webm;codecs=opus'
})
mediaRecorderRef.current = mediaRecorder
audioChunksRef.current = []

mediaRecorder.ondataavailable = (event) => {
if(event.data.size > 0){
audioChunksRef.current.push(event.data)
}
}

mediaRecorder.onstop = async () => {
const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
// Convert to WAV format (simplified - may need actual conversion)
await submitPronunciationAudio(audioBlob)
stream.getTracks().forEach(track => track.stop())
}

mediaRecorder.start()
setIsRecording(true)
} catch(e: any){
console.error('Recording error:', e)
alert('No se pudo acceder al micrófono. Por favor, permite el acceso al micrófono.')
}
}

function stopRecording(){
if(mediaRecorderRef.current && isRecording){
mediaRecorderRef.current.stop()
setIsRecording(false)
}
}

async function submitPronunciationAudio(audioBlob: Blob){
if(!activeQuiz?.data || activeQuiz.type !== 'pronunciation' || !activeQuiz.data.quizId) return
const sentence = activeQuiz.data.sentence
const quizId = activeQuiz.data.quizId

try {
// Convert audio to WAV format
// For now, we'll send WebM and let backend handle it, or convert using Web Audio API
const formData = new FormData()
formData.append('audio', audioBlob, 'recording.webm')
formData.append('sessionId', sessionId)
formData.append('referenceText', sentence)

const res = await fetch(`${API_BASE}/api/quiz/pronunciation/validate`, {
method: 'POST',
body: formData
})

if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { accuracy_score: data.accuracy_score, fluency_score: data.fluency_score, completeness_score: data.completeness_score, pronunciation_score: data.pronunciation_score, score: data.score, user_spoke: data.user_spoke } } }
    : msg
))
// Update activeQuiz for display
setActiveQuiz({
...activeQuiz,
result: {
accuracy_score: data.accuracy_score,
fluency_score: data.fluency_score,
completeness_score: data.completeness_score,
pronunciation_score: data.pronunciation_score,
score: data.score,
user_spoke: data.user_spoke
}
})
// Quiz completed - automatically trigger next turn
setTimeout(()=>{
setActiveQuiz(null)
waitingForQuizCompletion.current = true  // Set flag before sending empty message
send('')  // Empty message triggers agent to provide feedback and start next quiz
waitingForQuizCompletion.current = false  // Reset after sending
}, 2000)
}
} catch(e: any){
console.error('Validation error:', e)
alert('Error al validar la pronunciación. Por favor, intenta de nuevo.')
}
}

async function generateReadingQuiz(quizId: string){
try {
console.log(`[Frontend] 📞 Calling reading generate API (Quiz ID: ${quizId})...`)
const res = await fetch(`${API_BASE}/api/quiz/reading/generate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({ sessionId })
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
console.log(`[Frontend] ✅ Reading quiz response (Quiz ID: ${quizId}):`, data)
if(data.success){
// Update quiz in messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, type: 'reading', status: 'ready', data: { article_title: data.quiz.article_title, article_text: data.quiz.article_text, question: data.quiz.question, original_url: data.quiz.original_url, showQuestion: false } } }
    : msg
))
// Also set active quiz for interaction
setActiveQuiz({
type: 'reading',
data: {
article_title: data.quiz.article_title,
article_text: data.quiz.article_text,
question: data.quiz.question,
original_url: data.quiz.original_url,
showQuestion: false,
quizId
}
})
console.log(`[Frontend] ✅ Reading quiz ready (Quiz ID: ${quizId})`)
// After 5 seconds, show the question
setTimeout(()=>{
setActiveQuiz((prev: any) => prev ? {
...prev,
data: {
...prev.data,
showQuestion: true
}
} : null)
// Also update messages
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, data: { ...msg.quiz.data, showQuestion: true } } }
    : msg
))
}, 5000)
} else {
console.error(`[Frontend] ❌ Quiz generation failed (Quiz ID: ${quizId}):`, data)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: 'Failed to generate quiz' } }
    : msg
))
}
} catch(e: any){
console.error(`[Frontend] ❌ Quiz generation error (Quiz ID: ${quizId}):`, e)
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'error', error: e.message } }
    : msg
))
}
}

async function submitReadingAnswer(answer: string){
if(!activeQuiz?.data || activeQuiz.type !== 'reading' || !activeQuiz.data.quizId) return
const articleText = activeQuiz.data.article_text
const question = activeQuiz.data.question
const quizId = activeQuiz.data.quizId
try {
const res = await fetch(`${API_BASE}/api/quiz/reading/validate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({
sessionId,
userAnswer: answer,
articleText,
question
})
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { score: data.score, normalized_score: data.normalized_score, feedback: data.feedback, explanation: data.explanation, user_answer: answer } } }
    : msg
))
// Update activeQuiz for display
setActiveQuiz({
...activeQuiz,
result: {
score: data.score,
normalized_score: data.normalized_score,
feedback: data.feedback,
explanation: data.explanation,
user_answer: answer
}
})
// Quiz completed - automatically trigger next turn
setTimeout(()=>{
setActiveQuiz(null)
waitingForQuizCompletion.current = true  // Set flag before sending empty message
send('')  // Empty message triggers agent to provide feedback and start next quiz
waitingForQuizCompletion.current = false  // Reset after sending
}, 2000)
}
} catch(e: any){
console.error('Validation error:', e)
}
}

async function submitPodcastAnswer(answer: string){
if(!activeQuiz?.data || activeQuiz.type !== 'podcast' || !activeQuiz.data.quizId) return
const correctAnswer = activeQuiz.data.correct_answer
const quizId = activeQuiz.data.quizId
try {
const res = await fetch(`${API_BASE}/api/quiz/podcast/validate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({
sessionId,
userAnswer: answer,
correctAnswer
})
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { correct: data.correct, score: data.score, feedback: data.feedback, correct_answer: data.correct_answer, user_answer: answer } } }
    : msg
))
// Update activeQuiz for display
setActiveQuiz({
...activeQuiz,
result: {
correct: data.correct,
score: data.score,
feedback: data.feedback,
correct_answer: data.correct_answer,
user_answer: answer
}
})
// Quiz completed - automatically trigger next turn (for both correct and incorrect)
setTimeout(()=>{
  setActiveQuiz(null)
  waitingForQuizCompletion.current = true  // Set flag before sending empty message
  send('')  // Empty message triggers agent to provide feedback and start next quiz
  waitingForQuizCompletion.current = false  // Reset after sending
}, 2000)
}
} catch(e: any){
console.error('Validation error:', e)
}
}

async function submitUnitCompletionAnswer(answer: string){
if(!activeQuiz?.data || !activeQuiz.data.quizId) return
const maskedWord = activeQuiz.data.masked_word
const sentence = activeQuiz.data.sentence
const quizId = activeQuiz.data.quizId
try {
const res = await fetch(`${API_BASE}/api/quiz/unit-completion/validate`, {
method: 'POST',
headers: {'Content-Type': 'application/json'},
body: JSON.stringify({
sessionId,
userAnswer: answer,
maskedWord,
sentence: sentence || ''
})
})
if(!res.ok) throw new Error(`HTTP ${res.status}`)
const data = await res.json()
if(data.success){
// Update quiz in messages array with result
setMessages(m=>m.map(msg => 
  msg.quiz?.id === quizId 
    ? { ...msg, quiz: { ...msg.quiz, status: 'completed', result: { correct: data.correct, score: data.score, feedback: data.feedback, correct_answer: data.correct_answer, user_answer: answer } } }
    : msg
))
      // Also update activeQuiz for display
      setActiveQuiz({
        ...activeQuiz,
        result: {
          correct: data.correct,
          score: data.score,
          feedback: data.feedback,
          correct_answer: data.correct_answer,
          user_answer: answer
        }
      })
      // Always send completion notification to agent after showing result (for both correct and incorrect)
      // Give user 2 seconds to see the result, then auto-continue to next quiz
      setTimeout(()=>{
        setActiveQuiz(null)
        waitingForQuizCompletion.current = true  // Set flag before sending empty message
        send('')  // Empty message triggers agent to provide feedback and start next quiz
        waitingForQuizCompletion.current = false  // Reset after sending
      }, 2000)
}
} catch(e: any){
console.error('Validation error:', e)
}
}

return (
<div className="container">
<div className="card">
<div className="header">
<div>
<div style={{fontWeight:700,fontSize:28,color:'#2D2D2D',display:'flex',alignItems:'center',gap:8}}>
<img 
  src="https://cdn.jsdelivr.net/gh/wikimedia/commons@main/6/6e/Duo_from_Duolingo.svg" 
  alt="Duo" 
  style={{width: 40, height: 40, objectFit: 'contain'}}
  onError={(e) => {
    // Fallback to local file if CDN fails
    (e.target as HTMLImageElement).src = '/duo-icon.svg';
  }}
/>
<span>Chat with Hootie</span>
</div>
<div className="tiny">Learn languages with personalized AI tutoring</div>
</div>
</div>

<div className="messages" ref={accRef}>
{messages.map((m,i)=> {
  // Render quiz containers from messages array
  if(m.role === 'quiz' && m.quiz) {
    const quiz = m.quiz
    if(quiz.status === 'loading') {
      return (
        <div key={i} className="quiz-box" style={{
          border: '3px solid #1CB0F6',
          borderRadius: '20px',
          padding: '20px',
          margin: '16px 0',
          backgroundColor: '#F0F9FF',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
        }}>
          <div style={{textAlign: 'center', color: '#757575'}}>Loading quiz...</div>
        </div>
      )
    }
    if(quiz.status === 'error') {
      return (
        <div key={i} className="quiz-box" style={{
          border: '3px solid #DC143C',
          borderRadius: '20px',
          padding: '20px',
          margin: '16px 0',
          backgroundColor: '#FEF2F2',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
        }}>
          <div style={{color: '#DC143C'}}>Error: {quiz.error || 'Failed to load quiz'}</div>
        </div>
      )
    }
    // Render quiz from messages array - use activeQuiz.result if this is the active quiz, otherwise use quiz.result
    const isActive = activeQuiz?.data?.quizId === quiz.id
    const quizResult = isActive && activeQuiz?.result ? activeQuiz.result : quiz.result
    
    // If this quiz is active AND not yet completed, skip rendering here (let activeQuiz render it)
    // Only render from messages if: completed OR not active
    if(isActive && quiz.status !== 'completed') {
      return null  // Let activeQuiz handle it
    }
    
    // Render all quiz types from messages array so they persist
    // For completed quizzes, show results; for active quiz, show interactive UI
    if(quiz.type === 'unit_completion' && quiz.data) {
      return (
        <div key={i} className="quiz-box" style={{
          border: quizResult ? (quizResult.correct ? '3px solid #58CC02' : '3px solid #DC143C') : '3px solid #1CB0F6',
          borderRadius: '20px',
          padding: '20px',
          margin: '16px 0',
          backgroundColor: quizResult ? (quizResult.correct ? '#F0FDF4' : '#FEF2F2') : '#F0F9FF',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
        }}>
          <div style={{fontWeight: 600, marginBottom: '12px'}}>📝 Ejercicio de Completar Oración</div>
          <div style={{marginBottom: '12px', fontSize: '16px', lineHeight: '1.6'}}>
            {quiz.data.sentence}
          </div>
          {quiz.data.hint && !quizResult && (
            <div style={{fontSize: '12px', color: '#666', marginBottom: '8px', fontStyle: 'italic'}}>
              💡 Hint: {quiz.data.hint}
            </div>
          )}
          {!quizResult ? (
            <div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
              <input
                type="text"
                placeholder="Enter the missing word..."
                onKeyDown={(e)=>{
                  if(e.key === 'Enter' && (e.target as HTMLInputElement).value.trim() && isActive){
                    submitUnitCompletionAnswer((e.target as HTMLInputElement).value.trim())
                  }
                }}
                style={{
                  flex: 1,
                  padding: '12px 16px',
                  border: '2px solid #E5E5E5',
                  borderRadius: '16px',
                  fontSize: '15px',
                  fontFamily: 'inherit'
                }}
              />
              <button
                onClick={(e)=>{
                  const input = (e.currentTarget.parentElement?.querySelector('input') as HTMLInputElement)
                  if(input?.value.trim() && isActive){
                    submitUnitCompletionAnswer(input.value.trim())
                  }
                }}
                style={{
                  padding: '12px 24px',
                  background: '#58CC02',
                  color: 'white',
                  border: 'none',
                  borderRadius: '16px',
                  cursor: isActive ? 'pointer' : 'not-allowed',
                  fontSize: '15px',
                  fontWeight: 700,
                  fontFamily: 'inherit',
                  opacity: isActive ? 1 : 0.5
                }}
              >
                Send
              </button>
            </div>
          ) : (
            <div>
              <div style={{
                fontWeight: 600,
                fontSize: '18px',
                color: quizResult.correct ? '#58CC02' : '#DC143C',
                marginBottom: '12px',
                padding: '12px',
                background: quizResult.correct ? '#F0FDF4' : '#FEF2F2',
                borderRadius: '12px',
                border: quizResult.correct ? '2px solid #58CC02' : '2px solid #DC143C'
              }}>
                {quizResult.correct ? '✓ Correct!' : '✗ Incorrect'}
              </div>
              {quizResult.user_answer && (
                <div style={{
                  marginBottom: '12px',
                  padding: '10px',
                  background: quizResult.correct ? '#F0FDF4' : '#FFF5F5',
                  borderRadius: '8px',
                  border: quizResult.correct ? '1px solid #86EFAC' : '1px solid #FECACA'
                }}>
                  <strong style={{color: quizResult.correct ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: quizResult.correct ? '#065F46' : '#991B1B'}}>{quizResult.user_answer}</span>
                </div>
              )}
              <div style={{marginBottom: '12px', fontSize: '15px'}}>{quizResult.feedback}</div>
              {!quizResult.correct && quizResult.correct_answer && (
                <div style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: '#059669',
                  padding: '12px',
                  background: '#ECFDF5',
                  borderRadius: '8px',
                  border: '2px solid #10B981'
                }}>
                  <strong>Respuesta correcta:</strong> <span style={{fontSize: '18px'}}>{quizResult.correct_answer}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )
    }
    
    // For other quiz types, render completed ones with full content (images, etc.)
    // This ensures all completed quizzes stay visible with their full content
    if(quiz.status === 'completed' && quiz.result && quiz.data) {
      if(quiz.type === 'image_detection') {
        return (
          <div key={i} className="quiz-box" style={{
            border: quiz.result.correct ? '3px solid #58CC02' : '3px solid #DC143C',
            borderRadius: '20px',
            padding: '20px',
            margin: '16px 0',
            backgroundColor: quiz.result.correct ? '#F0FDF4' : '#FEF2F2',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
          }}>
            <div style={{fontWeight: 600, marginBottom: '12px'}}>🖼️ Detección de Imagen</div>
            {quiz.data.image_base64 && (
              <div style={{marginBottom: '16px', textAlign: 'center'}}>
                <img 
                  src={getImageDataUrl(quiz.data.image_base64)}
                  alt="Objeto para identificar"
                  style={{
                    maxWidth: '100%',
                    maxHeight: '300px',
                    borderRadius: '8px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}
                />
              </div>
            )}
            {quiz.data.image_url && !quiz.data.image_base64 && (
              <div style={{marginBottom: '16px', textAlign: 'center'}}>
                <img 
                  src={quiz.data.image_url}
                  alt="Objeto para identificar"
                  style={{
                    maxWidth: '100%',
                    maxHeight: '300px',
                    borderRadius: '8px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}
                />
              </div>
            )}
            <div style={{
              fontWeight: 600,
              fontSize: '18px',
              color: quiz.result.correct ? '#58CC02' : '#DC143C',
              marginBottom: '12px',
              padding: '12px',
              background: quiz.result.correct ? '#F0FDF4' : '#FEF2F2',
              borderRadius: '12px',
              border: quiz.result.correct ? '2px solid #58CC02' : '2px solid #DC143C'
            }}>
              {quiz.result.correct ? '✓ Correct!' : '✗ Incorrect'}
            </div>
            {quiz.result.user_answer && (
              <div style={{
                marginBottom: '12px',
                padding: '10px',
                background: quiz.result.correct ? '#F0FDF4' : '#FFF5F5',
                borderRadius: '8px',
                border: quiz.result.correct ? '1px solid #86EFAC' : '1px solid #FECACA'
              }}>
                <strong style={{color: quiz.result.correct ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: quiz.result.correct ? '#065F46' : '#991B1B'}}>{quiz.result.user_answer}</span>
              </div>
            )}
            <div style={{marginBottom: '12px', fontSize: '15px'}}>{quiz.result.feedback}</div>
            {!quiz.result.correct && quiz.result.correct_answer && (
              <div style={{
                fontSize: '16px',
                fontWeight: 600,
                color: '#059669',
                padding: '12px',
                background: '#ECFDF5',
                borderRadius: '8px',
                border: '2px solid #10B981'
              }}>
                <strong>Respuesta correcta:</strong> <span style={{fontSize: '18px'}}>{quiz.result.correct_answer}</span>
              </div>
            )}
          </div>
        )
      }
      
      if(quiz.type === 'keyword_match') {
        // Get English words from matches or pairs
        const allEnglishWords = quiz.data.pairs?.map((p: any) => p.english).filter(Boolean) || []
        const usedEnglishWords = quiz.data.matches?.map((m: any) => m.english).filter(Boolean) || []
        
        return (
          <div key={i} className="quiz-box" style={{
            border: quiz.result.all_correct ? '3px solid #58CC02' : '3px solid #1CB0F6',
            borderRadius: '20px',
            padding: '20px',
            margin: '16px 0',
            backgroundColor: quiz.result.all_correct ? '#F0FDF4' : '#F0F9FF',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
          }}>
            <div style={{fontWeight: 600, marginBottom: '16px'}}>🔗 Emparejamiento de Palabras Clave</div>
            <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px'}}>
              <div>
                <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '8px', color: '#666'}}>English</div>
                <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                  {allEnglishWords.map((eng: string, engIdx: number) => {
                    const isUsed = usedEnglishWords.includes(eng)
                    return (
                      <div
                        key={`eng-completed-${engIdx}`}
                        style={{
                          padding: '14px',
                          borderRadius: '16px',
                          background: isUsed ? '#F5F5F5' : '#FFFFFF',
                          border: '2px solid #E5E5E5',
                          textAlign: 'center',
                          fontSize: '15px',
                          fontWeight: 500,
                          opacity: isUsed ? 0.7 : 1
                        }}
                      >
                        {eng}
                      </div>
                    )
                  })}
                </div>
              </div>
              <div>
                <div style={{fontSize: '14px', fontWeight: 600, marginBottom: '8px', color: '#666'}}>Target Language</div>
                <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                  {quiz.data.pairs?.map((pair: any, idx: number) => {
                    const match = quiz.data.matches?.find((m: any) => m.spanish === pair.spanish)
                    const validationResult = quiz.result.results?.find((r: any) => r.spanish === pair.spanish)
                    const isCorrect = validationResult?.is_correct
                    const bgColor = isCorrect === true ? '#F0FDF4' : isCorrect === false ? '#FEF2F2' : '#FFFFFF'
                    const borderColor = isCorrect === true ? '#58CC02' : isCorrect === false ? '#DC143C' : '#E5E5E5'
                    
                    return (
                      <div
                        key={`span-completed-${idx}`}
                        style={{
                          padding: '14px',
                          borderRadius: '16px',
                          background: bgColor,
                          border: `3px solid ${borderColor}`,
                          color: '#2D2D2D',
                          textAlign: 'center',
                          fontSize: '15px',
                          fontWeight: 500,
                          minHeight: '40px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexDirection: 'column',
                          gap: '4px'
                        }}
                      >
                        <span>{pair.spanish}</span>
                        {match && (
                          <span style={{fontSize: '12px', color: '#666', fontWeight: 400}}>
                            → {match.english}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
            <div style={{
              fontWeight: 600,
              fontSize: '16px',
              color: quiz.result.all_correct ? '#2e7d32' : '#666',
              marginBottom: '12px',
              padding: '12px',
              background: quiz.result.all_correct ? '#F0FDF4' : '#F9F9F9',
              borderRadius: '12px',
              border: quiz.result.all_correct ? '2px solid #58CC02' : '2px solid #E5E5E5'
            }}>
              {quiz.result.all_correct ? '✓ ¡Perfecto! Todas correctas' : `Completado: ${quiz.result.correct_count}/${quiz.result.total} correctas`}
            </div>
            <div style={{fontSize: '14px', color: '#666'}}>
              Puntuación: <strong>{(quiz.result.score * 100).toFixed(0)}%</strong>
            </div>
          </div>
        )
      }
      
      if(quiz.type === 'reading') {
        return (
          <div key={i} className="quiz-box" style={{
            border: quiz.result.score >= 7 ? '3px solid #58CC02' : quiz.result.score >= 5 ? '3px solid #FF9600' : '3px solid #DC143C',
            borderRadius: '20px',
            padding: '20px',
            margin: '16px 0',
            backgroundColor: quiz.result.score >= 7 ? '#F0FDF4' : quiz.result.score >= 5 ? '#FFF8F0' : '#FEF2F2',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
          }}>
            <div style={{fontWeight: 600, marginBottom: '12px'}}>📖 Comprensión Lectora</div>
            {quiz.data.article_title && (
              <div style={{
                marginBottom: '12px',
                fontSize: '16px',
                fontWeight: 600,
                color: '#333',
                paddingBottom: '8px',
                borderBottom: '1px solid #ddd'
              }}>
                {quiz.data.article_title}
              </div>
            )}
            {quiz.data.original_url && (
              <div style={{
                marginBottom: '12px',
                fontSize: '12px',
                color: '#666',
                fontStyle: 'italic'
              }}>
                📰 Fuente: <a href={quiz.data.original_url} target="_blank" rel="noopener noreferrer" style={{color: '#1CB0F6', textDecoration: 'none'}}>{quiz.data.original_url}</a>
              </div>
            )}
            {quiz.data.article_text && (
              <div style={{
                marginBottom: '16px',
                padding: '12px',
                background: '#f9f9f9',
                borderRadius: '4px',
                fontSize: '14px',
                lineHeight: '1.8',
                maxHeight: '300px',
                overflowY: 'auto',
                whiteSpace: 'pre-wrap'
              }}>
                {quiz.data.article_text}
              </div>
            )}
            {quiz.data.question && (
              <div style={{
                marginBottom: '12px',
                padding: '12px',
                background: '#fff',
                borderRadius: '4px',
                border: '2px solid #2196f3',
                fontSize: '16px',
                fontWeight: 600
              }}>
                Question: {quiz.data.question}
              </div>
            )}
            <div style={{
              fontWeight: 600,
              fontSize: '18px',
              color: quiz.result.score >= 7 ? '#2e7d32' : quiz.result.score >= 5 ? '#f57c00' : '#c62828',
              marginBottom: '12px',
              padding: '12px',
              background: quiz.result.score >= 7 ? '#F0FDF4' : quiz.result.score >= 5 ? '#FFF8F0' : '#FEF2F2',
              borderRadius: '12px',
              border: quiz.result.score >= 7 ? '2px solid #58CC02' : quiz.result.score >= 5 ? '2px solid #FF9600' : '2px solid #DC143C'
            }}>
              Puntuación: {quiz.result.score}/10
            </div>
            {quiz.result.user_answer && (
              <div style={{
                marginBottom: '12px',
                padding: '10px',
                background: quiz.result.correct ? '#F0FDF4' : '#FFF5F5',
                borderRadius: '8px',
                border: quiz.result.correct ? '1px solid #86EFAC' : '1px solid #FECACA'
              }}>
                <strong style={{color: quiz.result.correct ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: quiz.result.correct ? '#065F46' : '#991B1B'}}>{quiz.result.user_answer}</span>
              </div>
            )}
            {quiz.result.feedback && (
              <div style={{marginBottom: '12px', fontSize: '15px'}}>{quiz.result.feedback}</div>
            )}
            {quiz.result.explanation && (
              <div style={{
                fontSize: '14px',
                color: '#666',
                padding: '10px',
                background: '#f5f5f5',
                borderRadius: '8px',
                marginTop: '8px'
              }}>
                {quiz.result.explanation}
              </div>
            )}
          </div>
        )
      }
      
      if(quiz.type === 'podcast' && quiz.data) {
        return (
          <div key={i} className="quiz-box" style={{
            border: quiz.result.correct ? '3px solid #58CC02' : '3px solid #DC143C',
            borderRadius: '20px',
            padding: '20px',
            margin: '16px 0',
            backgroundColor: quiz.result.correct ? '#F0FDF4' : '#FEF2F2',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
          }}>
            <div style={{fontWeight: 600, marginBottom: '12px'}}>🎧 Comprensión Auditiva (Podcast)</div>
            {quiz.data.audio_base64 && (
              <div style={{marginBottom: '16px'}}>
                <audio
                  controls
                  style={{width: '100%', marginBottom: '12px'}}
                  src={`data:audio/mp3;base64,${quiz.data.audio_base64}`}
                >
                  Tu navegador no soporta el elemento de audio.
                </audio>
              </div>
            )}
            {quiz.data.conversation && (
              <div style={{
                marginBottom: '16px',
                padding: '12px',
                background: '#f5f5f5',
                borderRadius: '4px',
                fontSize: '14px',
                lineHeight: '1.6',
                whiteSpace: 'pre-line'
              }}>
                {quiz.data.conversation}
              </div>
            )}
            {quiz.data.question && (
              <div style={{
                marginBottom: '12px',
                padding: '12px',
                background: '#fff',
                borderRadius: '4px',
                border: '2px solid #2196f3',
                fontSize: '16px',
                fontWeight: 600
              }}>
                Question: {quiz.data.question}
              </div>
            )}
            <div style={{
              fontWeight: 600,
              fontSize: '18px',
              color: quiz.result.correct ? '#58CC02' : '#DC143C',
              marginBottom: '12px',
              padding: '12px',
              background: quiz.result.correct ? '#F0FDF4' : '#FEF2F2',
              borderRadius: '12px',
              border: quiz.result.correct ? '2px solid #58CC02' : '2px solid #DC143C'
            }}>
              {quiz.result.correct ? '✓ Correct!' : '✗ Incorrect'}
            </div>
            {quiz.result.user_answer && (
              <div style={{
                marginBottom: '12px',
                padding: '10px',
                background: quiz.result.correct ? '#F0FDF4' : '#FFF5F5',
                borderRadius: '8px',
                border: quiz.result.correct ? '1px solid #86EFAC' : '1px solid #FECACA'
              }}>
                <strong style={{color: quiz.result.correct ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: quiz.result.correct ? '#065F46' : '#991B1B'}}>{quiz.result.user_answer}</span>
              </div>
            )}
            {quiz.result.feedback && (
              <div style={{marginBottom: '12px', fontSize: '15px'}}>{quiz.result.feedback}</div>
            )}
            {!quiz.result.correct && quiz.result.correct_answer && (
              <div style={{
                fontSize: '16px',
                fontWeight: 600,
                color: '#059669',
                padding: '12px',
                background: '#ECFDF5',
                borderRadius: '8px',
                border: '2px solid #10B981'
              }}>
                <strong>Respuesta correcta:</strong> <span style={{fontSize: '18px'}}>{quiz.result.correct_answer}</span>
              </div>
            )}
          </div>
        )
      }
      
      // Pronunciation quiz - show full content
      if (quiz.type === 'pronunciation' && quiz.status === 'completed') {
        const pronunciationScore = quiz.result.pronunciation_score || (quiz.result.score ? quiz.result.score * 100 : 0)
        return (
          <div key={i} className="quiz-box" style={{
            border: pronunciationScore >= 80 ? '3px solid #58CC02' : pronunciationScore >= 60 ? '3px solid #FF9600' : '3px solid #DC143C',
            borderRadius: '20px',
            padding: '20px',
            margin: '16px 0',
            backgroundColor: pronunciationScore >= 80 ? '#F0FDF4' : pronunciationScore >= 60 ? '#FFF8F0' : '#FEF2F2',
            boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)'
          }}>
            <div style={{fontWeight: 700, marginBottom: '16px', fontSize: '18px', color: '#2D2D2D'}}>
              🎤 Práctica de Pronunciación
            </div>
            
            {/* Original sentence - always show */}
            {quiz.data.sentence && (
              <div style={{
                marginBottom: '16px',
                padding: '16px',
                background: '#fff',
                borderRadius: '12px',
                border: '2px solid #1CB0F6',
                fontSize: '18px',
                fontWeight: 600,
                color: '#2D2D2D',
                textAlign: 'center'
              }}>
                {quiz.data.sentence}
              </div>
            )}
            
            {/* Results */}
            {quiz.result && (
              <div>
                <div style={{
                  fontWeight: 600,
                  fontSize: '18px',
                  color: pronunciationScore >= 80 ? '#58CC02' : pronunciationScore >= 60 ? '#FF9600' : '#DC143C',
                  marginBottom: '12px',
                  padding: '12px',
                  background: pronunciationScore >= 80 ? '#F0FDF4' : pronunciationScore >= 60 ? '#FFF8F0' : '#FEF2F2',
                  borderRadius: '12px',
                  border: pronunciationScore >= 80 ? '2px solid #58CC02' : pronunciationScore >= 60 ? '2px solid #FF9600' : '2px solid #DC143C'
                }}>
                  Puntuación: {pronunciationScore.toFixed(0)}%
                </div>
                
                {quiz.result.accuracy_score !== undefined && (
                  <div style={{marginBottom: '12px', fontSize: '14px', color: '#666'}}>
                    <div>Precisión: {quiz.result.accuracy_score.toFixed(0)}%</div>
                    <div>Fluidez: {quiz.result.fluency_score.toFixed(0)}%</div>
                    <div>Completitud: {quiz.result.completeness_score.toFixed(0)}%</div>
                  </div>
                )}
                
                {quiz.result.user_spoke && quiz.result.user_spoke !== 'Audio recording' && (
                  <div style={{
                    marginBottom: '12px',
                    padding: '10px',
                    background: pronunciationScore >= 80 ? '#F0FDF4' : '#FFF5F5',
                    borderRadius: '8px',
                    border: pronunciationScore >= 80 ? '1px solid #86EFAC' : '1px solid #FECACA'
                  }}>
                    <strong style={{color: pronunciationScore >= 80 ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: pronunciationScore >= 80 ? '#065F46' : '#991B1B', fontStyle: 'italic'}}>"{quiz.result.user_spoke}"</span>
                  </div>
                )}
                
                {quiz.result.feedback && (
                  <div style={{marginBottom: '12px', fontSize: '15px', color: '#2D2D2D'}}>
                    {quiz.result.feedback}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      }
      
      // Other quiz types - show simplified summary
      return (
        <div key={i} className="quiz-box" style={{
          border: '3px solid #E5E5E5',
          borderRadius: '20px',
          padding: '20px',
          margin: '16px 0',
          backgroundColor: '#F9F9F9',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
          opacity: 0.9
        }}>
          <div style={{fontWeight: 600, marginBottom: '12px', fontSize: '14px', color: '#666'}}>
            Quiz completado
          </div>
          {quiz.result.score !== undefined && (
            <div style={{fontSize: '14px', color: '#666'}}>
              Puntuación: <strong>{(quiz.result.score * 100).toFixed(0)}%</strong>
            </div>
          )}
        </div>
      )
    }
    
    return null  // Let legacy activeQuiz rendering handle active/interactive quizzes
  }
  // Regular message
  return <div key={i} className={`msg ${m.role==='assistant'?'assistant':'user'}`}>{m.content}</div>
})}
{/* Render active quiz (the one user is currently interacting with) */}
{activeQuiz && activeQuiz.type === 'unit_completion' && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result ? (activeQuiz.result.correct ? '3px solid #58CC02' : '3px solid #DC143C') : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result ? (activeQuiz.result.correct ? '#F0FDF4' : '#FEF2F2') : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '12px'}}>📝 Ejercicio de Completar Oración</div>
<div style={{marginBottom: '12px', fontSize: '16px', lineHeight: '1.6'}}>
{activeQuiz.data.sentence}
</div>
{activeQuiz.data.hint && (
<div style={{fontSize: '12px', color: '#666', marginBottom: '8px', fontStyle: 'italic'}}>
💡 Hint: {activeQuiz.data.hint}
</div>
)}
{!activeQuiz.result ? (
<div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
<input
type="text"
placeholder="Enter the missing word..."
onKeyDown={(e)=>{
if(e.key === 'Enter' && (e.target as HTMLInputElement).value.trim()){
submitUnitCompletionAnswer((e.target as HTMLInputElement).value.trim())
}}}
style={{
flex: 1,
padding: '12px 16px',
border: '2px solid #E5E5E5',
borderRadius: '16px',
fontSize: '15px',
fontFamily: 'inherit',
transition: 'all 0.2s ease'
}}
/>
<button
onClick={()=>{
const input = document.querySelector('.quiz-box input') as HTMLInputElement
if(input?.value.trim()){
submitUnitCompletionAnswer(input.value.trim())
}
}}
style={{
padding: '12px 24px',
background: '#58CC02',
color: 'white',
border: 'none',
borderRadius: '16px',
cursor: 'pointer',
fontSize: '15px',
fontWeight: 700,
textTransform: 'uppercase',
letterSpacing: '0.5px',
fontFamily: 'inherit',
transition: 'all 0.2s ease',
boxShadow: '0 4px 12px rgba(88, 204, 2, 0.3)'
}}
>
Send
</button>
</div>
) : (
<div>
<div style={{
fontWeight: 600,
color: activeQuiz.result.correct ? '#58CC02' : '#DC143C',
marginBottom: '8px'
}}>
{activeQuiz.result.correct ? '✓ Correct!' : '✗ Incorrect'}
</div>
<div style={{marginBottom: '8px'}}>{activeQuiz.result.feedback}</div>
{!activeQuiz.result.correct && (
<div style={{fontSize: '14px', color: '#666'}}>
Respuesta correcta: <strong>{activeQuiz.result.correct_answer}</strong>
</div>
)}
</div>
)}
</div>
)}
{activeQuiz && activeQuiz.type === 'keyword_match' && activeQuiz.data && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result?.all_correct ? '3px solid #58CC02' : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result?.all_correct ? '#F0FDF4' : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '16px'}}>🔗 Emparejamiento de Palabras Clave</div>
{!activeQuiz.result ? (
<>
<div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px'}}>
<div>
<div style={{fontSize: '14px', fontWeight: 600, marginBottom: '8px', color: '#666'}}>English (Drag to match)</div>
<div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
{shuffledEnglish.map((eng: string, engIdx: number) => {
const isUsed = activeQuiz.data.matches?.some((m: any) => m.english === eng)
return (
<div
key={`eng-${engIdx}`}
draggable={!isUsed}
onDragStart={(e) => handleKeywordDragStart(e, eng, 'english')}
style={{
padding: '14px',
borderRadius: '16px',
background: isUsed ? '#F5F5F5' : '#FFFFFF',
border: isUsed ? '2px solid #E5E5E5' : '2px solid #1CB0F6',
cursor: isUsed ? 'not-allowed' : 'grab',
opacity: isUsed ? 0.5 : 1,
textAlign: 'center',
fontSize: '15px',
fontWeight: 500,
boxShadow: isUsed ? 'none' : '0 2px 4px rgba(0, 0, 0, 0.1)'
}}
>
{eng}
</div>
)
})}
</div>
</div>
<div>
<div style={{fontSize: '14px', fontWeight: 600, marginBottom: '8px', color: '#666'}}>Target Language (Drop here)</div>
<div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
{activeQuiz.data.pairs.map((pair: any, idx: number) => {
const match = activeQuiz.data.matches?.find((m: any) => m.spanish === pair.spanish)
// Check validation result if available
const validationResult = activeQuiz.result?.results?.find((r: any) => r.spanish === pair.spanish)
const isCorrect = validationResult?.is_correct
const bgColor = isCorrect === true ? '#F0FDF4' : isCorrect === false ? '#FEF2F2' : match ? '#FFF8F0' : '#FFFFFF'
const textColor = isCorrect === true || isCorrect === false ? '#FFFFFF' : '#2D2D2D'
const borderColor = isCorrect === true ? '#58CC02' : isCorrect === false ? '#DC143C' : match ? '#FF9600' : '#1CB0F6'
return (
<div
key={`span-${idx}`}
onDragOver={handleKeywordDragOver}
onDrop={(e) => handleKeywordDrop(e, pair.spanish)}
style={{
padding: '14px',
borderRadius: '16px',
background: bgColor,
border: `3px solid ${borderColor}`,
color: textColor,
textAlign: 'center',
fontSize: '15px',
fontWeight: 500,
minHeight: '40px',
display: 'flex',
alignItems: 'center',
justifyContent: 'center',
cursor: 'pointer'
}}
>
<span>{pair.spanish}</span>
{match && <span style={{marginLeft: '8px', fontSize: '12px'}}>→ {match.english}</span>}
</div>
)
})}
</div>
</div>
</div>
{activeQuiz.data.matches?.length === 5 && !activeQuiz.result?.all_correct && (
<div style={{marginTop: '16px', textAlign: 'center'}}>
<button
onClick={submitKeywordMatch}
style={{
padding: '10px 20px',
background: '#2196f3',
color: 'white',
border: 'none',
borderRadius: '4px',
cursor: 'pointer',
fontSize: '14px',
fontWeight: 600
}}
>
{activeQuiz.result ? 'Verificar de Nuevo' : 'Verificar Respuestas'}
</button>
</div>
)}
{/* Show auto-continue message when all correct */}
{activeQuiz.result?.all_correct && (
<div style={{
marginTop: '16px',
padding: '12px',
background: '#F0FDF4',
borderRadius: '8px',
border: '2px solid #58CC02',
textAlign: 'center',
color: '#059669',
fontWeight: 600
}}>
¡Perfecto! Continuando automáticamente...
</div>
)}
</>
) : (
<div>
<div style={{
fontWeight: 600,
fontSize: '16px',
color: activeQuiz?.result?.all_correct ? '#2e7d32' : '#666',
marginBottom: '12px'
}}>
{activeQuiz?.result?.all_correct ? '✓ ¡Perfecto! Todas correctas' : `Completado: ${activeQuiz?.result?.correct_count}/${activeQuiz?.result?.total} correctas`}
</div>
<div style={{fontSize: '14px', color: '#666'}}>
Puntuación: {((activeQuiz?.result?.score || 0) * 100).toFixed(0)}%
</div>
</div>
)}
</div>
)}
{activeQuiz && activeQuiz.type === 'image_detection' && activeQuiz.data && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result ? (activeQuiz.result.correct ? '3px solid #58CC02' : '3px solid #DC143C') : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result ? (activeQuiz.result.correct ? '#F0FDF4' : '#FEF2F2') : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '12px'}}>🖼️ Detección de Imagen</div>
{activeQuiz.data.image_base64 && (
              <div style={{marginBottom: '16px', textAlign: 'center'}}>
                <img 
                  src={getImageDataUrl(activeQuiz.data.image_base64)}
                  alt="Objeto para identificar"
                  style={{
                    maxWidth: '100%',
                    maxHeight: '300px',
                    borderRadius: '8px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}
                />
              </div>
            )}
{activeQuiz.data.image_url && !activeQuiz.data.image_base64 && (
<div style={{marginBottom: '16px', textAlign: 'center'}}>
<img 
src={activeQuiz.data.image_url}
alt="Objeto para identificar"
style={{
maxWidth: '100%',
maxHeight: '300px',
borderRadius: '8px',
boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
}}
/>
</div>
)}
<div style={{marginBottom: '12px', fontSize: '16px', textAlign: 'center'}}>
What is this? Enter the name:
</div>
{!activeQuiz.result ? (
<div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
<input
type="text"
placeholder="Enter the word..."
onKeyDown={(e)=>{
if(e.key === 'Enter' && (e.target as HTMLInputElement).value.trim()){
submitImageDetectionAnswer((e.target as HTMLInputElement).value.trim())
}}}
style={{
flex: 1,
padding: '12px 16px',
border: '2px solid #E5E5E5',
borderRadius: '16px',
fontSize: '15px',
fontFamily: 'inherit',
transition: 'all 0.2s ease'
}}
/>
<button
onClick={()=>{
const input = document.querySelector('.quiz-box input') as HTMLInputElement
if(input?.value.trim()){
submitImageDetectionAnswer(input.value.trim())
}
}}
style={{
padding: '12px 24px',
background: '#58CC02',
color: 'white',
border: 'none',
borderRadius: '16px',
cursor: 'pointer',
fontSize: '15px',
fontWeight: 700,
textTransform: 'uppercase',
letterSpacing: '0.5px',
fontFamily: 'inherit',
transition: 'all 0.2s ease',
boxShadow: '0 4px 12px rgba(88, 204, 2, 0.3)'
}}
>
Send
</button>
</div>
) : (
<div>
<div style={{
fontWeight: 600,
fontSize: '18px',
color: activeQuiz.result.correct ? '#58CC02' : '#DC143C',
marginBottom: '12px',
padding: '12px',
background: activeQuiz.result.correct ? '#F0FDF4' : '#FEF2F2',
borderRadius: '12px',
border: activeQuiz.result.correct ? '2px solid #58CC02' : '2px solid #DC143C'
}}>
{activeQuiz.result.correct ? '✓ Correct!' : '✗ Incorrect'}
</div>
{activeQuiz.result.user_answer && (
<div style={{
marginBottom: '12px',
padding: '10px',
background: activeQuiz.result.correct ? '#F0FDF4' : '#FFF5F5',
borderRadius: '8px',
border: activeQuiz.result.correct ? '1px solid #86EFAC' : '1px solid #FECACA'
}}>
<strong style={{color: activeQuiz.result.correct ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: activeQuiz.result.correct ? '#065F46' : '#991B1B'}}>{activeQuiz.result.user_answer}</span>
</div>
)}
<div style={{
marginBottom: '12px',
fontSize: '15px',
color: '#2D2D2D'
}}>
{activeQuiz.result.feedback}
</div>
{!activeQuiz.result.correct && (
<div style={{
fontSize: '16px',
fontWeight: 600,
color: '#059669',
padding: '12px',
background: '#ECFDF5',
borderRadius: '8px',
border: '2px solid #10B981',
marginBottom: '12px'
}}>
<strong>Respuesta correcta:</strong> <span style={{fontSize: '18px'}}>{activeQuiz.result.correct_answer}</span>
</div>
)}
{activeQuiz.result.correct && (
<div style={{marginTop: '16px', textAlign: 'center'}}>
<button
onClick={()=>{
waitingForQuizCompletion.current = false
setActiveQuiz(null)
send('')
}}
style={{
padding: '12px 24px',
background: '#58CC02',
color: 'white',
border: 'none',
borderRadius: '16px',
cursor: 'pointer',
fontSize: '15px',
fontWeight: 700,
textTransform: 'uppercase',
letterSpacing: '0.5px',
fontFamily: 'inherit',
boxShadow: '0 4px 12px rgba(88, 204, 2, 0.3)'
}}
>
Continuar →
</button>
</div>
)}
</div>
)}
</div>
)}
{activeQuiz && activeQuiz.type === 'podcast' && activeQuiz.data && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result ? (activeQuiz.result.correct ? '3px solid #58CC02' : '3px solid #DC143C') : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result ? (activeQuiz.result.correct ? '#F0FDF4' : '#FEF2F2') : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '12px'}}>🎧 Comprensión Auditiva (Podcast)</div>
{activeQuiz.data.audio_base64 && (
<div style={{marginBottom: '16px'}}>
<audio
controls
style={{width: '100%', marginBottom: '12px'}}
src={`data:audio/mp3;base64,${activeQuiz.data.audio_base64}`}
>
Tu navegador no soporta el elemento de audio.
</audio>
</div>
)}
<div style={{
marginBottom: '16px',
padding: '12px',
background: '#f5f5f5',
borderRadius: '4px',
fontSize: '14px',
lineHeight: '1.6',
whiteSpace: 'pre-line'
}}>
{activeQuiz.data.conversation}
</div>
{activeQuiz.data.showQuestion && !activeQuiz.result && (
<>
<div style={{marginBottom: '12px', fontSize: '16px', fontWeight: 600}}>
Question: {activeQuiz.data.question}
</div>
<div style={{display: 'flex', gap: '8px', alignItems: 'center'}}>
<input
type="text"
placeholder="Enter your answer..."
onKeyDown={(e)=>{
if(e.key === 'Enter' && (e.target as HTMLInputElement).value.trim()){
submitPodcastAnswer((e.target as HTMLInputElement).value.trim())
}}}
style={{
flex: 1,
padding: '12px 16px',
border: '2px solid #E5E5E5',
borderRadius: '16px',
fontSize: '15px',
fontFamily: 'inherit',
transition: 'all 0.2s ease'
}}
/>
<button
onClick={()=>{
const input = document.querySelector('.quiz-box input') as HTMLInputElement
if(input?.value.trim()){
submitPodcastAnswer(input.value.trim())
}
}}
style={{
padding: '12px 24px',
background: '#58CC02',
color: 'white',
border: 'none',
borderRadius: '16px',
cursor: 'pointer',
fontSize: '15px',
fontWeight: 700,
textTransform: 'uppercase',
letterSpacing: '0.5px',
fontFamily: 'inherit',
transition: 'all 0.2s ease',
boxShadow: '0 4px 12px rgba(88, 204, 2, 0.3)'
}}
>
Send
</button>
</div>
</>
)}
{!activeQuiz.data.showQuestion && !activeQuiz.result && (
<div style={{textAlign: 'center', color: '#666', fontSize: '14px', fontStyle: 'italic'}}>
Read the conversation. The question will appear shortly...
</div>
)}
{activeQuiz.result && (
<div>
<div style={{
fontWeight: 600,
color: activeQuiz.result.correct ? '#58CC02' : '#DC143C',
marginBottom: '8px'
}}>
{activeQuiz.result.correct ? '✓ Correct!' : '✗ Incorrect'}
</div>
<div style={{marginBottom: '8px'}}>{activeQuiz.result.feedback}</div>
{!activeQuiz.result.correct && (
<div style={{fontSize: '14px', color: '#666'}}>
Respuesta correcta: <strong>{activeQuiz.result.correct_answer}</strong>
</div>
)}
</div>
)}
</div>
)}
{activeQuiz && activeQuiz.type === 'pronunciation' && activeQuiz.data && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result ? (activeQuiz.result.pronunciation_score >= 80 ? '3px solid #58CC02' : activeQuiz.result.pronunciation_score >= 60 ? '3px solid #FF9600' : '3px solid #DC143C') : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result ? (activeQuiz.result.pronunciation_score >= 80 ? '#F0FDF4' : activeQuiz.result.pronunciation_score >= 60 ? '#FFF8F0' : '#FEF2F2') : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '12px'}}>🎤 Práctica de Pronunciación</div>
<div style={{
marginBottom: '16px',
padding: '16px',
background: '#fff',
borderRadius: '4px',
fontSize: '18px',
textAlign: 'center',
fontWeight: 500,
lineHeight: '1.6',
border: '2px solid #e0e0e0'
}}>
{activeQuiz.data.sentence}
</div>
{!activeQuiz.result ? (
<div style={{textAlign: 'center'}}>
<div style={{marginBottom: '16px', fontSize: '14px', color: '#666'}}>
Lee la frase en voz alta usando el botón de grabación
</div>
{!isRecording ? (
<button
onClick={startRecording}
style={{
padding: '12px 24px',
background: '#f44336',
color: 'white',
border: 'none',
borderRadius: '50%',
cursor: 'pointer',
fontSize: '24px',
width: '64px',
height: '64px',
display: 'flex',
alignItems: 'center',
justifyContent: 'center',
margin: '0 auto',
boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
}}
>
🎤
</button>
) : (
<div>
<button
onClick={stopRecording}
style={{
padding: '12px 24px',
background: '#4caf50',
color: 'white',
border: 'none',
borderRadius: '8px',
cursor: 'pointer',
fontSize: '16px',
fontWeight: 600,
boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
}}
>
⏹ Detener grabación
</button>
<div style={{marginTop: '12px', fontSize: '14px', color: '#f44336', fontWeight: 600}}>
● Grabando...
</div>
</div>
)}
</div>
) : (
<div>
<div style={{
fontWeight: 600,
fontSize: '18px',
color: activeQuiz.result.pronunciation_score >= 80 ? '#2e7d32' : activeQuiz.result.pronunciation_score >= 60 ? '#f57c00' : '#c62828',
marginBottom: '12px',
textAlign: 'center'
}}>
Puntuación: {activeQuiz.result.pronunciation_score.toFixed(1)}/100
</div>
<div style={{
display: 'grid',
gridTemplateColumns: 'repeat(3, 1fr)',
gap: '12px',
marginBottom: '16px'
}}>
<div style={{textAlign: 'center', padding: '8px', background: '#f5f5f5', borderRadius: '4px'}}>
<div style={{fontSize: '12px', color: '#666', marginBottom: '4px'}}>Precisión</div>
<div style={{fontSize: '16px', fontWeight: 600}}>{activeQuiz.result.accuracy_score.toFixed(1)}</div>
</div>
<div style={{textAlign: 'center', padding: '8px', background: '#f5f5f5', borderRadius: '4px'}}>
<div style={{fontSize: '12px', color: '#666', marginBottom: '4px'}}>Fluidez</div>
<div style={{fontSize: '16px', fontWeight: 600}}>{activeQuiz.result.fluency_score.toFixed(1)}</div>
</div>
<div style={{textAlign: 'center', padding: '8px', background: '#f5f5f5', borderRadius: '4px'}}>
<div style={{fontSize: '12px', color: '#666', marginBottom: '4px'}}>Completitud</div>
<div style={{fontSize: '16px', fontWeight: 600}}>{activeQuiz.result.completeness_score.toFixed(1)}</div>
</div>
</div>
{activeQuiz.result.user_spoke && activeQuiz.result.user_spoke !== 'Audio recording' && (
<div style={{
marginTop: '12px',
padding: '10px',
background: activeQuiz.result.pronunciation_score >= 80 ? '#F0FDF4' : '#FFF5F5',
borderRadius: '8px',
border: activeQuiz.result.pronunciation_score >= 80 ? '1px solid #86EFAC' : '1px solid #FECACA'
}}>
<strong style={{color: activeQuiz.result.pronunciation_score >= 80 ? '#059669' : '#DC143C'}}>Tu respuesta:</strong> <span style={{color: activeQuiz.result.pronunciation_score >= 80 ? '#065F46' : '#991B1B', fontStyle: 'italic'}}>"{activeQuiz.result.user_spoke}"</span>
</div>
)}
</div>
)}
</div>
)}
{activeQuiz && activeQuiz.type === 'reading' && activeQuiz.data && !messages.some(m => m.quiz?.id === activeQuiz.data?.quizId && m.quiz?.status === 'completed') && (
<div className="quiz-box" style={{
border: activeQuiz.result ? (activeQuiz.result.score >= 7 ? '3px solid #58CC02' : activeQuiz.result.score >= 5 ? '3px solid #FF9600' : '3px solid #DC143C') : '3px solid #1CB0F6',
borderRadius: '20px',
padding: '20px',
margin: '16px 0',
backgroundColor: activeQuiz.result ? (activeQuiz.result.score >= 7 ? '#F0FDF4' : activeQuiz.result.score >= 5 ? '#FFF8F0' : '#FEF2F2') : '#F0F9FF',
boxShadow: '0 4px 12px rgba(0, 0, 0, 0.08)'
}}>
<div style={{fontWeight: 600, marginBottom: '12px'}}>📖 Comprensión Lectora</div>
<div style={{
marginBottom: '12px',
fontSize: '16px',
fontWeight: 600,
color: '#333',
paddingBottom: '8px',
borderBottom: '1px solid #ddd'
}}>
{activeQuiz.data.article_title}
</div>
{activeQuiz.data.original_url && (
<div style={{
marginBottom: '12px',
fontSize: '12px',
color: '#666',
fontStyle: 'italic'
}}>
📰 Fuente: <a href={activeQuiz.data.original_url} target="_blank" rel="noopener noreferrer" style={{color: '#1CB0F6', textDecoration: 'none'}}>{activeQuiz.data.original_url}</a>
</div>
)}
<div style={{
marginBottom: '16px',
padding: '12px',
background: '#f9f9f9',
borderRadius: '4px',
fontSize: '14px',
lineHeight: '1.8',
maxHeight: '300px',
overflowY: 'auto',
whiteSpace: 'pre-wrap'
}}>
{activeQuiz.data.article_text}
</div>
{activeQuiz.data.showQuestion && !activeQuiz.result && (
<>
<div style={{
marginBottom: '12px',
padding: '12px',
background: '#fff',
borderRadius: '4px',
border: '2px solid #2196f3',
fontSize: '16px',
fontWeight: 600
}}>
❓ {activeQuiz.data.question}
</div>
<div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
<textarea
placeholder="Enter your answer here..."
onKeyDown={(e)=>{
if(e.key === 'Enter' && e.ctrlKey && (e.target as HTMLTextAreaElement).value.trim()){
submitReadingAnswer((e.target as HTMLTextAreaElement).value.trim())
}}}
style={{
width: '100%',
minHeight: '80px',
padding: '8px',
border: '1px solid #ccc',
borderRadius: '4px',
fontSize: '14px',
fontFamily: 'inherit',
resize: 'vertical'
}}
/>
<div style={{fontSize: '12px', color: '#666', marginTop: '-4px'}}>
Ctrl + Enter to send
</div>
<button
onClick={()=>{
const textarea = document.querySelector('.quiz-box textarea') as HTMLTextAreaElement
if(textarea?.value.trim()){
submitReadingAnswer(textarea.value.trim())
}
}}
style={{
padding: '10px 20px',
background: '#2196f3',
color: 'white',
border: 'none',
borderRadius: '4px',
cursor: 'pointer',
fontSize: '14px',
fontWeight: 600
}}
>
Send Answer
</button>
</div>
</>
)}
{!activeQuiz.data.showQuestion && !activeQuiz.result && (
<div style={{textAlign: 'center', color: '#666', fontSize: '14px', fontStyle: 'italic', padding: '12px'}}>
Read the article carefully. The question will appear shortly...
</div>
)}
{activeQuiz.result && (
<div>
<div style={{
fontWeight: 600,
fontSize: '20px',
color: activeQuiz.result.score >= 7 ? '#2e7d32' : activeQuiz.result.score >= 5 ? '#f57c00' : '#c62828',
marginBottom: '12px',
textAlign: 'center'
}}>
Puntuación: {activeQuiz.result.score.toFixed(1)}/10
</div>
<div style={{
marginBottom: '12px',
padding: '12px',
background: '#fff',
borderRadius: '4px',
fontSize: '14px',
lineHeight: '1.6'
}}>
<div style={{fontWeight: 600, marginBottom: '4px'}}>📝 Feedback:</div>
{activeQuiz.result.feedback}
</div>
<div style={{
padding: '12px',
background: '#f5f5f5',
borderRadius: '4px',
fontSize: '13px',
lineHeight: '1.6',
color: '#666'
}}>
<div style={{fontWeight: 600, marginBottom: '4px'}}>💡 Explicación:</div>
{activeQuiz.result.explanation}
</div>
</div>
)}
</div>
)}
{loading && <div className="msg assistant typing">The teacher is thinking…</div>}
</div>

<div className="inputRow">
<input value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Type here... (Enter to send)" onKeyDown={e=>{ if(e.key==='Enter'){ send(draft) }}} />
<button onClick={()=>send(draft)} disabled={loading}>Send</button>
</div>
</div>
</div>
)
}