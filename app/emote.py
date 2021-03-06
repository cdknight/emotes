from PIL import ImageSequence as PILImageSequence
from PIL import Image as PILImage
import os
import json
from io import BytesIO
import requests
from emotes.wsgi import app
from emotes.app.models import *

class EmoteWrapper():
    """Pull emotes from local storage, db, or api and create a nice abstraction over it"""
    
    API_PROVIDERS = ["discord", "twitch"]

    def __init__(self, namespace, emote, width, height, tg=False):
        self.namespace = namespace
        self.emote = emote
        self.width = width
        self.height = height
        self.tg = tg


    def fetch(self):
        """Fetch the emote from the appropriate source and return a BytesIO for returning in flask"""
        img = None
        if self.namespace == None:
            # Local
            return self.__fetch_local()

        root_namespace = self.namespace.split("/")[0]
        if root_namespace in EmoteWrapper.API_PROVIDERS:
            # API
            img = self.__fetch_api()
        else:
            # DB
            img = self.__fetch_db()
        
        #return self.__pillow_to_bytesio(self.__resize_emote(img))
        if img:
            return img

        return None

    def __resize_emote(self, image, _type):
        """"Resizes the emote so it appears similar to a 32x32 discord emoji. Returns a BytesIO"""
        
        # Get the resize % for the image
        resize_width = self.width / image.width
        resize_height = self.height/ image.height
        resize_value = min(resize_width, resize_height)
        def __emote():
            image_resized = image.resize((int(resize_value * image.width), int(resize_value * image.height)), resample=PILImage.HAMMING)
            i = BytesIO()
            image_resized.save(i, format='PNG', quality=100)
            i.seek(0)
            return (i, 'png')

        def __aemote():
            # Rules to start a new image processing task:
            # The animated emote hasn't been resized yet
            # The animated emote was requested under a size that hasn't been scaled yet
            metadata = image.info

            # Extract the frames for resizing
            frames_resize = []
            for frame in PILImageSequence.Iterator(image):
                frames_resize.append(frame.resize((int(resize_value * image.width), int(resize_value * image.height)), resample=PILImage.BOX))
            first = next(iter(frames_resize))
            first.info = metadata
            i = BytesIO()
            first.save(i, format='GIF', quality=100, save_all=True, append_images=frames_resize)
            i.seek(0)
            return (i, 'gif')
        switch = {
            'emote': __emote,
            'aemote': __aemote
        }
        func = switch.get(_type, lambda: "Cannot find type")
        return func()

    def __pillow_to_bytesio(self, pillow_img):
        """Return a BytesIO from a Pillow so we can render stuff in Flask easily"""
        i = BytesIO()
        pillow_img.save(i, 'WEBP', quality=100)
        i.seek(0)
        return i

    def __fetch_api(self):
        """Returns a BytesIO image"""
        split = self.namespace.split("/")
        service = split[0]
        sub = split[1]

        def __twitch():
            headers = {
                'Accept': 'application/vnd.twitchtv.v5+json',
                'Client-ID': app.config['TWITCH_CLIENT_ID']
            }
            streamer_id = None
            emote_set = None
            emote_id = None
            with requests.get(f'https://api.twitch.tv/kraken/users?login={sub}', headers=headers) as r:
                d = r.json()
                print(d)
                if 'users' in d: 
                    if '_id' in d['users'][0]:
                        streamer_id = d['users'][0]['_id']
            with requests.get(f'https://api.twitchemotes.com/api/v4/channels/{streamer_id}') as r:
                d = r.json()
                if 'emotes' in d:
                    for i in d['emotes']:
                        if i['code'] == self.emote:
                            emote_id = i['id']
                            print(emote_id)
            try:
                with requests.get(f'https://static-cdn.jtvnw.net/emoticons/v1/{emote_id}/4.0') as r:
                    k = BytesIO(r.content)
                    k.seek(0)
                    i = PILImage.open(k)
                    return self.__resize_emote(i, 'emote')
            except:
                return None


        return {
            'twitch': __twitch
        }.get(service)()

    def __fetch_local(self):
        """
        Fetch local emotes from the emotes/* directory. 
        The __fetch_local scans that directory for 
        your given emote name (since local emotes don't have a namespace, they might later).
        
        It returns the BytesIO object for the image, resized, for easy usage within flask, like 
        all __fetch_\w+ methods.
        """

        local_emotes = os.listdir(app.config["EMOTES_PATH"])
        for emote_name in local_emotes:
            if self.emote == emote_name:
                with open(os.path.join(app.config["EMOTES_PATH"], emote_name, "info.json")) as emote_info_file:
                    emote_info = json.load(emote_info_file)

                emote_path = os.path.join(app.config["EMOTES_PATH"], emote_name, emote_info.get("path"))
                emote_type = emote_info.get("type")

                try:
                    image = Image.select().where(Image.original == emote_path).get()
                    resized_image = image.size(self.width, self.height, webp=self.tg)
                    print(f"The original image is {image.original}")
                    if resized_image.processed:
                        with open(os.path.join(app.config["UPLOADS_PATH"], resized_image.path), 'rb') as emote_img_f:
                            emote_file = BytesIO(emote_img_f.read())


                        if emote_type == "aemote":
                            emote_type = 'gif'
                        else:
                            emote_type = 'png'
                        return (emote_file, emote_type if not resized_image.webp else 'webp')

                except Image.DoesNotExist:
                    image = Image(original=emote_path)
                    image.save()

                    resized_image = image.size(self.width, self.height, webp=self.tg)

                    print("Here at image.doesnotexist")
                    if resized_image.processed:
                        with open(os.path.join(app.config["UPLOADS_PATH"], resized_image.path), 'rb') as emote_img_f:
                            emote_file = BytesIO(emote_img_f.read())


                        if emote_type == "aemote":
                            emote_type = 'gif'
                        else:
                            emote_type = 'png'
                        return (emote_file, emote_type if not resized_image.webp else 'webp')

                    return 'processing'


        
    def __fetch_db(self):
        namespace = Namespace.from_path(self.namespace)
        if not namespace: 
            return None
        emote = namespace.emotes.select().where(Emote.slug == self.emote).first()
        if not emote:
            return None

        emote_resize = emote.image.size(self.width, self.height, webp=self.tg)
        if emote_resize.processed: # We want to return something like a "msg": "Image processing." if the image hasn't processed yet.
            with open(os.path.join(app.config["UPLOADS_PATH"], emote_resize.path), 'rb') as emote_img_f:
                emote_file = BytesIO(emote_img_f.read())
            return (emote_file, emote.info['type'] if not emote_resize.webp else "webp")

        return 'processing'
