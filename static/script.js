const ws = new WebSocket("ws://localhost:6789");
ws.onmessage = e=>{
    const data = JSON.parse(e.data);
    appendMessage(`${data.platform}:${data.user_id}`, data.text,false);
    appendMessage("小悠", data.response,true);
    if(data.tts){ new Audio(data.tts).play(); }
    saveMessage(`${data.platform}:${data.user_id}`, data.text, data.platform);
    saveMessage("小悠", data.response, data.platform);
}

async function sendMessage(msg){
    appendMessage("你", msg);
    saveMessage("你", msg, "web");
    ws.send(JSON.stringify({platform:"web",user_id:"web",message:msg}));
}
