import os, requests, json

class AIConfigError(Exception): pass
class AIServiceError(Exception): pass

class AIService:
    def __init__(self):
        self.base=os.getenv('AI_BASE_URL','').rstrip('/')
        self.key=os.getenv('AI_API_KEY','')
        self.model=os.getenv('AI_MODEL','')
        self.configured=bool(self.base and self.key and self.model)
    def _call(self,messages,temperature=.2):
        if not self.configured:
            raise AIConfigError('AI provider is not configured yet. Add AI_BASE_URL, AI_API_KEY and AI_MODEL to backend/.env.')
        try:
            r=requests.post(self.base+'/chat/completions',headers={'Authorization':f'Bearer {self.key}','Content-Type':'application/json'},json={'model':self.model,'messages':messages,'temperature':temperature},timeout=120)
            r.raise_for_status(); data=r.json(); return data['choices'][0]['message']['content']
        except Exception as e: raise AIServiceError(str(e))
    def generate(self,text,generation_type,language,style,custom=None):
        task=custom or generation_type.replace('_',' ')
        system=f'''You are Study With Me AI. Be accurate, friendly and source-grounded. Answer in {language}. Response style: {style}. Do not invent information not supported by the supplied source. Clearly say when something is uncertain. Preserve technical terms. User requested: {task}.'''
        user=f'''SOURCE CONTENT:\n{text[:180000]}\n\nCreate the requested output. For documents, cite page/chapter references when they can be determined from the source text.'''
        return self._call([{'role':'system','content':system},{'role':'user','content':user}])
    def chat(self,message,source,language,style,image_data_url=None):
        system=f'''You are Study With Me AI, a friendly learning assistant. Respond in {language} using {style} style. If source content is supplied, prioritize it and do not invent document facts. If you cannot answer from the source, say so and then clearly label any general knowledge.'''
        content=[]
        if source: content.append({'type':'text','text':'SOURCE/CONTEXT:\n'+source[:180000]})
        content.append({'type':'text','text':message})
        if image_data_url: content.append({'type':'image_url','image_url':{'url':image_data_url}})
        return self._call([{'role':'system','content':system},{'role':'user','content':content}])
