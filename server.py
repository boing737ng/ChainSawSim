from flask import Flask, render_template_string, request, Response
import json
from app import ChainsawAudioModel

app = Flask(__name__)

# Глобальный экземпляр модели
model = None
throttle_position = 0.0  # Текущая позиция дросселя (0.0 - 1.0)

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Симулятор Звука Бензопилы</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            margin-bottom: 20px;
            color: #ff9500;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
        }
        .main-panel {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        .control-section {
            flex: 1;
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 20px;
            backdrop-filter: blur(10px);
        }
        .section-title {
            font-size: 1.2em;
            color: #ff9500;
            margin-bottom: 15px;
            border-bottom: 2px solid #ff9500;
            padding-bottom: 5px;
        }
        .param-group {
            margin-bottom: 15px;
        }
        .param-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
            font-size: 0.9em;
        }
        .param-name {
            color: #aaa;
        }
        .param-value {
            color: #4CAF50;
            font-weight: bold;
            min-width: 60px;
            text-align: right;
        }
        input[type="range"] {
            width: 100%;
            height: 8px;
            border-radius: 4px;
            background: #333;
            outline: none;
            -webkit-appearance: none;
        }
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #ff9500;
            cursor: pointer;
            transition: background 0.2s;
        }
        input[type="range"]::-webkit-slider-thumb:hover {
            background: #ffb74d;
        }
        .throttle-container {
            text-align: center;
            padding: 30px;
            background: rgba(255,149,0,0.1);
            border-radius: 15px;
            margin-bottom: 20px;
        }
        .throttle-display {
            font-size: 3em;
            color: #ff9500;
            margin: 20px 0;
        }
        .rpm-display {
            font-size: 2em;
            color: #4CAF50;
        }
        .btn {
            padding: 15px 40px;
            font-size: 1.2em;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            margin: 10px;
            transition: all 0.3s;
        }
        .btn-start {
            background: #4CAF50;
            color: white;
        }
        .btn-start:hover {
            background: #45a049;
        }
        .btn-stop {
            background: #f44336;
            color: white;
        }
        .btn-stop:hover {
            background: #da190b;
        }
        .btn-reset {
            background: #2196F3;
            color: white;
        }
        .btn-reset:hover {
            background: #1976D2;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 10px;
        }
        .status-on {
            background: #4CAF50;
            box-shadow: 0 0 10px #4CAF50;
        }
        .status-off {
            background: #f44336;
        }
        .params-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 15px;
        }
        .checkbox-container {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-top: 5px;
        }
        input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        @media (max-width: 768px) {
            .main-panel {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🪚 Симулятор Звука Бензопилы</h1>
        
        <div class="throttle-container">
            <div>
                <span class="status-indicator" id="statusIndicator"></span>
                <span id="statusText">Остановлено</span>
            </div>
            <div class="throttle-display">
                Дроссель: <span id="throttleValue">0</span>%
            </div>
            <div class="rpm-display">
                RPM: <span id="rpmValue">0</span>
            </div>
            <div style="margin-top: 20px;">
                <button class="btn btn-start" onclick="startAudio()">▶ Запустить</button>
                <button class="btn btn-stop" onclick="stopAudio()">⏹ Стоп</button>
                <button class="btn btn-reset" onclick="resetParams()">↺ Сброс</button>
            </div>
            <div style="margin-top: 30px;">
                <label style="font-size: 1.5em;">Педаль газа (удерживайте):</label><br>
                <input type="range" id="throttleSlider" min="0" max="100" value="0" 
                       style="width: 300px; height: 50px; margin-top: 20px;"
                       oninput="updateThrottle(this.value)"
                       ontouchstart="handleThrottleStart(event)"
                       ontouchend="handleThrottleEnd(event)">
            </div>
        </div>

        <div class="main-panel">
            <div class="control-section">
                <div class="section-title">🔥 Двигатель и Сгорание</div>
                <div class="params-grid" id="engineParams"></div>
            </div>
            
            <div class="control-section">
                <div class="section-title">⛽ Топливо и Смесь</div>
                <div class="params-grid" id="fuelParams"></div>
            </div>
        </div>

        <div class="main-panel">
            <div class="control-section">
                <div class="section-title">⚙️ Механика и Зазоры</div>
                <div class="params-grid" id="mechanicalParams"></div>
            </div>
            
            <div class="control-section">
                <div class="section-title">🔗 Цепь и Резка</div>
                <div class="params-grid" id="chainParams"></div>
            </div>
        </div>

        <div class="control-section">
            <div class="section-title">🔊 Акустика и Среда</div>
            <div class="params-grid" id="acousticParams"></div>
        </div>
    </div>

    <script>
        let audioContext = null;
        let isRunning = false;
        let throttlePos = 0.0;
        let currentRpm = 0;
        let params = {};
        
        // Параметры сгруппированы по категориям
        const paramGroups = {
            engine: {
                bore_mm: {min: 30, max: 60, step: 0.5, unit: 'мм'},
                stroke_mm: {min: 20, max: 45, step: 0.5, unit: 'мм'},
                compression_ratio: {min: 6, max: 13, step: 0.1, unit: ''},
                port_timing_deg: {min: 100, max: 170, step: 1, unit: '°'},
                crankcase_volume_cm3: {min: 150, max: 400, step: 5, unit: 'см³'},
                exhaust_length_mm: {min: 100, max: 400, step: 5, unit: 'мм'},
                muffler_volume_cm3: {min: 400, max: 1200, step: 10, unit: 'см³'},
                reed_stiffness: {min: 0.5, max: 2.0, step: 0.05, unit: ''}
            },
            fuel: {
                fuel_octane: {min: 80, max: 100, step: 1, unit: ''},
                oil_ratio_50_1: {min: 0.5, max: 2.0, step: 0.05, unit: ''},
                air_fuel_ratio: {min: 10, max: 18, step: 0.1, unit: ''},
                ethanol_pct: {min: 0, max: 85, step: 1, unit: '%'},
                combustion_efficiency: {min: 0.6, max: 1.0, step: 0.01, unit: ''}
            },
            mechanical: {
                piston_mass_g: {min: 150, max: 350, step: 5, unit: 'г'},
                conrod_length_mm: {min: 70, max: 130, step: 2, unit: 'мм'},
                bearing_clearance_um: {min: 5, max: 50, step: 1, unit: 'мкм'},
                piston_cylinder_clearance_um: {min: 10, max: 60, step: 1, unit: 'мкм'},
                piston_ring_tension_N: {min: 10, max: 30, step: 1, unit: 'Н'},
                governor_max_rpm: {min: 10000, max: 16000, step: 100, unit: 'об/мин'},
                idle_rpm: {min: 2000, max: 4000, step: 50, unit: 'об/мин'},
                throttle_tau_s: {min: 0.05, max: 0.3, step: 0.01, unit: 'с'}
            },
            chain: {
                sprocket_teeth: {min: 5, max: 10, step: 1, unit: 'зубьев'},
                chain_pitch_mm: {min: 2.5, max: 4.0, step: 0.05, unit: 'мм'},
                guide_bar_len_cm: {min: 25, max: 70, step: 1, unit: 'см'},
                chain_tension_N: {min: 20, max: 80, step: 1, unit: 'Н'},
                cutting_load: {min: 0, max: 1, step: 0.05, unit: ''},
                chain_wear_factor: {min: 0, max: 1, step: 0.05, unit: ''}
            },
            acoustic: {
                housing_resonance_hz: {min: 200, max: 500, step: 5, unit: 'Гц'},
                housing_damping: {min: 0.05, max: 0.5, step: 0.01, unit: ''},
                ambient_temp_c: {min: -20, max: 50, step: 1, unit: '°C'},
                air_pressure_kpa: {min: 80, max: 120, step: 1, unit: 'кПа'},
                mic_distance_m: {min: 0.5, max: 10, step: 0.1, unit: 'м'},
                directional_gain_db: {min: -10, max: 20, step: 0.5, unit: 'дБ'}
            }
        };

        function createParamInput(key, config, value) {
            return `
                <div class="param-group">
                    <div class="param-label">
                        <span class="param-name">${key}</span>
                        <span class="param-value" id="val_${key}">${value}${config.unit}</span>
                    </div>
                    <input type="range" id="${key}" min="${config.min}" max="${config.max}" 
                           step="${config.step}" value="${value}"
                           oninput="updateParam('${key}', this.value, '${config.unit}')">
                </div>
            `;
        }

        function initParams() {
            fetch('/api/params')
                .then(r => r.json())
                .then(data => {
                    params = data.params;
                    
                    document.getElementById('engineParams').innerHTML = 
                        Object.entries(paramGroups.engine)
                            .map(([k, v]) => createParamInput(k, v, params[k]))
                            .join('');
                    
                    document.getElementById('fuelParams').innerHTML = 
                        Object.entries(paramGroups.fuel)
                            .map(([k, v]) => createParamInput(k, v, params[k]))
                            .join('');
                    
                    document.getElementById('mechanicalParams').innerHTML = 
                        Object.entries(paramGroups.mechanical)
                            .map(([k, v]) => createParamInput(k, v, params[k]))
                            .join('');
                    
                    document.getElementById('chainParams').innerHTML = 
                        Object.entries(paramGroups.chain)
                            .map(([k, v]) => createParamInput(k, v, params[k]))
                            .join('');
                    
                    document.getElementById('acousticParams').innerHTML = 
                        Object.entries(paramGroups.acoustic)
                            .map(([k, v]) => createParamInput(k, v, params[k]))
                            .join('');
                });
        }

        function updateParam(key, value, unit) {
            document.getElementById(`val_${key}`).textContent = value + unit;
            params[key] = parseFloat(value);
            
            fetch('/api/update_param', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key, value: parseFloat(value)})
            });
        }

        function updateThrottle(value) {
            throttlePos = parseFloat(value) / 100;
            document.getElementById('throttleValue').textContent = value;
            
            fetch('/api/throttle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({position: throttlePos})
            });
        }

        function handleThrottleStart(e) {
            e.preventDefault();
            updateThrottle(e.target.value);
        }

        function handleThrottleEnd(e) {
            e.preventDefault();
            updateThrottle(0);
            document.getElementById('throttleSlider').value = 0;
        }

        async function startAudio() {
            if (isRunning) return;
            
            try {
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                await audioContext.resume();
                
                const stream = await fetch('/api/audio_stream').then(r => r.body);
                const reader = stream.getReader();
                
                isRunning = true;
                document.getElementById('statusIndicator').className = 'status-indicator status-on';
                document.getElementById('statusText').textContent = 'Работает';
                
                let audioData = [];
                
                while (isRunning) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    
                    const wavBlob = new Blob([value], {type: 'audio/wav'});
                    const arrayBuffer = await wavBlob.arrayBuffer();
                    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
                    
                    const source = audioContext.createBufferSource();
                    source.buffer = audioBuffer;
                    source.connect(audioContext.destination);
                    source.start();
                    
                    // Обновляем RPM
                    fetch('/api/rpm')
                        .then(r => r.json())
                        .then(data => {
                            document.getElementById('rpmValue').textContent = Math.round(data.rpm);
                        });
                }
            } catch (e) {
                console.error('Audio error:', e);
                alert('Ошибка воспроизведения: ' + e.message);
            }
        }

        function stopAudio() {
            isRunning = false;
            if (audioContext) {
                audioContext.close();
                audioContext = null;
            }
            document.getElementById('statusIndicator').className = 'status-indicator status-off';
            document.getElementById('statusText').textContent = 'Остановлено';
            document.getElementById('rpmValue').textContent = '0';
        }

        function resetParams() {
            fetch('/api/reset_params', {method: 'POST'})
                .then(() => location.reload());
        }

        // Инициализация при загрузке
        initParams();
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/params')
def get_params():
    global model
    if model is None:
        model = ChainsawAudioModel()
    return {'params': model.params}

@app.route('/api/update_param', methods=['POST'])
def update_param():
    global model
    data = request.json
    key = data['key']
    value = data['value']
    
    if model is None:
        model = ChainsawAudioModel()
    
    if key in model.params:
        model.params[key] = value
        try:
            model._validate_params()
        except ValueError as e:
            return {'error': str(e)}, 400
    
    return {'success': True}

@app.route('/api/throttle', methods=['POST'])
def set_throttle():
    global throttle_position
    data = request.json
    throttle_position = float(data.get('position', 0))
    throttle_position = max(0, min(1, throttle_position))
    return {'success': True, 'position': throttle_position}

@app.route('/api/rpm')
def get_rpm():
    global model, throttle_position
    if model is None:
        model = ChainsawAudioModel()
    
    # Расчет текущего RPM на основе позиции дросселя
    idle = model.params['idle_rpm']
    max_rpm = model.params['governor_max_rpm']
    current_rpm = idle + (max_rpm - idle) * throttle_position
    return {'rpm': current_rpm}

@app.route('/api/audio_stream')
def audio_stream():
    global model, throttle_position
    
    if model is None:
        model = ChainsawAudioModel()
    
    def generate():
        sr = 44100
        chunk_duration = 0.1  # 100ms chunks
        
        while True:
            try:
                audio_data, _ = model.generate_chunk(
                    duration=chunk_duration,
                    sr=sr,
                    throttle_position=throttle_position
                )
                wav_bytes = model.audio_to_wav_bytes(audio_data, sr)
                yield wav_bytes
            except Exception as e:
                print(f"Audio generation error: {e}")
                break
    
    return Response(generate(), mimetype='audio/wav')

@app.route('/api/reset_params', methods=['POST'])
def reset_params():
    global model
    model = ChainsawAudioModel()
    return {'success': True}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
