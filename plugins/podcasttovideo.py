import streamlit as st
from app import Plugin
from global_vars import t, translations
import os
import subprocess
import tempfile
from pydub import AudioSegment
from pydub.silence import split_on_silence
from plugins.transcript import TranscriptPlugin
from plugins.articletovideo import ArticletovideoPlugin
from plugins.imggen import ImggenPlugin
from plugins.ragllm import RagllmPlugin
import traceback

# Add translations for this plugin
translations["en"].update({
    "podcasttovideo": "Podcast to Video",
    "select_podcast": "Select a podcast file (audio or video)",
    "process_podcast": "Process Podcast",
    "processing": "Processing...",
    "video_generated": "Video generated successfully!",
    "error_processing": "Error during processing: ",
    "step_saving_file": "Saving the uploaded file...",
    "step_extracting_audio": "Extracting audio from the file...",
    "step_splitting_audio": "Splitting audio into chunks...",
    "step_transcribing_audio": "Transcribing audio chunks...",
    "step_generating_images": "Generating images for each transcription...",
    "step_assembling_video": "Assembling the final video...",
    "step_generating_prompts": "Generating prompts for each transcription...",
    "step_generating_images": "Generating images for each transcription...",
    "generated_prompts": "Generated Prompts",
})

translations["fr"].update({
    "podcasttovideo": "Podcast en Vidéo",
    "select_podcast": "Sélectionnez un fichier podcast (audio ou vidéo)",
    "process_podcast": "Traiter le Podcast",
    "processing": "Traitement en cours...",
    "video_generated": "Vidéo générée avec succès !",
    "error_processing": "Erreur lors du traitement : ",
    "step_saving_file": "Enregistrement du fichier téléchargé...",
    "step_extracting_audio": "Extraction de l'audio du fichier...",
    "step_splitting_audio": "Découpage de l'audio en segments...",
    "step_transcribing_audio": "Transcription des segments audio...",
    "step_generating_images": "Génération des images pour chaque transcription...",
    "step_assembling_video": "Assemblage de la vidéo finale...",
    "step_generating_prompts": "Génération des prompts pour chaque transcription...",
    "step_generating_images": "Génération des images pour chaque transcription...",
    "generated_prompts": "Prompts générés",
})

class PodcasttovideoPlugin(Plugin):
    def __init__(self, name, plugin_manager):
        super().__init__(name, plugin_manager)
        self.transcript_plugin = TranscriptPlugin("transcript", plugin_manager)
        self.articlevideo_plugin = ArticletovideoPlugin("articletovideo", plugin_manager)
        self.imggen_plugin = ImggenPlugin("imggen", plugin_manager)
        self.ragllm_plugin = RagllmPlugin("ragllm", plugin_manager)

    def get_config_fields(self):
        return {
            "output_dir": {
                "type": "text",
                "label": t("output_directory"),
                "default": "~/Videos/PodcastToVideo"
            },
            "min_silence_len": {
                "type": "number",
                "label": "Minimum silence length (ms)",
                "default": 500
            },
            "silence_thresh": {
                "type": "number",
                "label": "Silence threshold (dB)",
                "default": -40
            }
        }

    def get_tabs(self):
        return [{"name": t("podcasttovideo"), "plugin": "podcasttovideo"}]

    def extract_audio(self, input_file, output_file):
        ffmpeg_command = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            output_file
        ]
        subprocess.run(ffmpeg_command, check=True)

    def split_audio(self, audio_file, min_silence_len, silence_thresh):
        audio = AudioSegment.from_wav(audio_file)
        chunks = split_on_silence(
            audio,
            min_silence_len=min_silence_len,
            silence_thresh=silence_thresh
        )
        return chunks

    def transcribe_chunks(self, chunks, config):
        transcriptions = []
        progress_bar = st.progress(0)
        total_chunks = len(chunks)

        for i, chunk in enumerate(chunks):
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_audio:
                chunk.export(temp_audio.name, format="wav")
                transcript = self.transcript_plugin.transcribe_video(
                    temp_audio.name,
                    "txt",
                    config['transcript']['whisper_path'],
                    config['transcript']['whisper_model'],
                    config['transcript']['ffmpeg_path'],
                    config['common']['language']
                )
                transcriptions.append(transcript)
                os.unlink(temp_audio.name)
                progress_bar.progress((i + 1) / total_chunks)
        return transcriptions

    def generate_images(self, transcriptions, config):
        prompts = []
        image_paths = []
        progress_bar = st.progress(0)
        total_transcriptions = len(transcriptions)

        # Étape 1 : Génération des prompts
        st.info(t("step_generating_prompts"))
        for i, text in enumerate(transcriptions):
            prompt = self.articlevideo_plugin.generate_image_prompt(text)
            prompts.append(prompt)

            # Mise à jour de la barre de progression pour les prompts
            progress_bar.progress((i + 1) / total_transcriptions)

        prompts_text = "\n\n".join(prompts)
        st.text_area(t("generated_prompts"), prompts_text, height=300)

        # Libérer la mémoire en déchargeant le modèle
        self.articlevideo_plugin.unload_ollama_model()

        # Réinitialiser la barre de progression pour la génération des images
        progress_bar = st.progress(0)

        # Étape 2 : Génération des images
        st.info(t("step_generating_images"))
        for i, prompt in enumerate(prompts):
            output_dir = os.path.expanduser(config['podcasttovideo']['output_dir'])
            image_path = os.path.join(output_dir, f"image_{i}.png")
            self.articlevideo_plugin.generate_image(prompt, image_path)
            image_paths.append(image_path)

            # Mise à jour de la barre de progression pour les images
            progress_bar.progress((i + 1) / total_transcriptions)

        cols = st.columns(3)
        for i, image_path in enumerate(image_paths):
            with cols[i % 3]:
                st.image(image_path)

        return image_paths

    def run(self, config):
        st.header(t("podcasttovideo"))

        use_zoom_and_transitions = st.checkbox(t("use_zoom_and_transitions"), value=True, key="use_zoom_transitions_checkbox")
        uploaded_file = st.file_uploader(t("select_podcast"), type=["mp3", "wav", "mp4", "avi", "mov", "mkv"])

        if uploaded_file is not None and st.button(t("process_podcast")):
            with st.spinner(t("processing")):
                try:
                    output_dir = os.path.expanduser(config['podcasttovideo']['output_dir'])
                    os.makedirs(output_dir, exist_ok=True)
                    # Save uploaded file
                    st.info(t("step_saving_file"))
                    input_file = os.path.join(tempfile.gettempdir(), uploaded_file.name)
                    with open(input_file, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    # Extract audio
                    st.info(t("step_extracting_audio"))
                    audio_file = os.path.join(tempfile.gettempdir(), "extracted_audio.wav")
                    self.extract_audio(input_file, audio_file)

                    # Split audio into chunks
                    st.info(t("step_splitting_audio"))
                    min_silence_len = int(config['podcasttovideo']['min_silence_len'])
                    silence_thresh = int(config['podcasttovideo']['silence_thresh'])
                    chunks = self.split_audio(
                        audio_file,
                        min_silence_len,
                        silence_thresh
                    )
                    audio_paths = []
                    for i, chunk in enumerate(chunks):
                        chunk_path = os.path.join(output_dir, f"chunk_{i}.wav")
                        chunk.export(chunk_path, format="wav")
                        audio_paths.append(chunk_path)

                    # Transcribe chunks
                    st.info(t("step_transcribing_audio"))
                    transcriptions = self.transcribe_chunks(chunks, config)

                    # Generate images for each transcription
                    st.info(t("step_generating_images"))
                    image_paths = self.generate_images(transcriptions, config)

                    # Assemble final video
                    st.info(t("step_assembling_video"))
                    output_path = os.path.join(output_dir, "final_video.mp4")
                    self.articlevideo_plugin.assemble_final_video(
                        use_zoom_and_transitions=use_zoom_and_transitions,
                        audio_paths=audio_paths,
                        image_paths=image_paths,
                        output_path=output_path
                    )

                except Exception as e:
                    error_details = traceback.format_exc()
                    st.error(f"{t('error_processing')}\n{str(e)}\n\nDetails:\n{error_details}")

                finally:
                    # Clean up temporary files
                    if os.path.exists(input_file):
                        os.unlink(input_file)
                    if os.path.exists(audio_file):
                        os.unlink(audio_file)
