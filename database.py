try:
    import Image
except ImportError:
    from PIL import Image

import copy
import imghdr
import os
import re
import shutil

import pytesseract

from flickr import download_flickr_images, upload_image

# FOLDER PATHS
LOADING_ZONE = "loading_zone"
TEXT_PATH = "completed_text_files"
DEST_PATH = "completed_files"

# SPECIAL FILES
COUNT_FILE = "filecount.txt"
METADATA_FILE = "metadata.txt"

# METADATA FILES
METADATA_FILE_NAME_FIELD = "File Name"
METADATA_FIELDS = [
    METADATA_FILE_NAME_FIELD,
    "Name of Picture Taker (Last, First)",
    "Date Added (mm/dd/yyyy)",
    "Box Number",
    "Folder",
    "Page Number",
    "Title",
    "Creator",
    "Subject",
    "Description",
    "Publisher",
    "Type",
    "Format",
    "Source",
    "Language",
    "Tags and/or Keywords",
    "Rights Management",
    "Comments/Notes about File"
]

def indent_print(message, indent=0):
    print(4 * indent * " " + message)

# DOCUMENT FUNCTIONS

class Document:
    def __init__(self, image_file):
        self.image_file = image_file
        self.image_path = os.path.join(DEST_PATH, image_file)
        self.filenumber = re.search("document(.*)image", self.image_path).group(1)
        self.text_file = self.text_file_name()
        self.text_path = os.path.join(TEXT_PATH, self.text_file)
        if self.has_text_file():
            with open(self.text_path) as file:
                self.text = file.read()
        else:
            self.text = ""
        self.metadata = {}
        self.metadata_list = self.get_metadata_list()
        self.search_meta_matches = {}
        self.search_text_matches = []
    def get_metadata_list(self):
        list_from_dict = []
        for field in METADATA_FIELDS:
            if field in self.metadata:
                list_from_dict.append([field, self.metadata[field]])
            else:
                list_from_dict.append([field, ''])
        for field, value in sorted(self.metadata.items()):
            if field not in METADATA_FIELDS:
                list_from_dict.append([field, value])
        return list_from_dict
    def text_file_name(self):
        return "document" + str(self.filenumber) + "text.txt"
    def has_image_file(self):
        return os.path.exists(self.image_path)
    def has_text_file(self):
        return os.path.exists(self.text_path)
    def has_files(self):
        return self.has_text_file()
    def write_text_file(self):
        with open(self.text_path, "w") as file:
            file.write(self.text)
    def metadata_string(self):
        lines = []
        # add all defined fields first
        for field in METADATA_FIELDS:
            if field in self.metadata:
                lines.append(field + ": [" + self.metadata[field] + "]")
            else:
                lines.append(field + ": []")
        # then add the remainder alphabetically
        for field, value in sorted(self.metadata.items()):
            if field not in METADATA_FIELDS:
                lines.append(field + ": [" + value + "]")
        return "\n".join(lines)

def create_new_metadata(file):
    metadata = {}
    for field in METADATA_FIELDS:
        metadata[field] = ""
    metadata[METADATA_FILE_NAME_FIELD] = file
    return metadata

def metadata_to_dict(section):
    metadata = {}
    # FIXME assumes each line is a field
    for line in section.splitlines():
        line = line.strip()
        if line == "":
            continue
        field, value = line.split(":", maxsplit=1)
        # remove trailing spaces and the [brackets]
        value = value.strip()[1:-1]
        metadata[field] = value
    return metadata

def read_documents():
    documents = []
    with open(METADATA_FILE) as file:
        metadata_text = file.read()
    for section in metadata_text.split("\n\n"):
        if section.strip() == "":
            continue
        metadata = metadata_to_dict(section)
        # create the Document using the File Name
        doc = Document(metadata[METADATA_FILE_NAME_FIELD])
        doc.metadata = metadata
        # only add it to the list of documents if those files actually exist
        if doc.has_files():
            documents.append(doc)
    return documents

def search_term_in_metadata_and_text(term):
    matches = set()
    if term:
        term = term.lower()
        for instance in read_documents():
            index = 0
            for key in instance.metadata:
                if term in instance.metadata[key].lower():
                    if instance not in matches:
                        matches.add(instance)
            if term in instance.text.lower():
                while index < len(instance.text):
                    index = instance.text.lower().find(term, index)
                    if index == -1:
                        break
                    instance.search_text_matches.append(index)
                    index += len(term)
                if instance not in matches:
                    matches.add(instance)
        if not matches:
            matches = "No search matches found."
    return matches

# OCR FUNCTIONS

def text_file_exists(path):
    for file in os.listdir(path):
        if file.endswith('.txt'):
            return True
    return False

def read_folder_metadata(path):
    text_exists = text_file_exists(path)
    if text_exists:
        for file in os.listdir(path):
            if file.endswith('.txt'):
                with open(os.path.join(path, file)) as file:
                    return metadata_to_dict(file.read())

def request_new_file_number():
    with open(COUNT_FILE) as file:
        file_number = int(file.read())
    with open(COUNT_FILE, "w") as file:
        file.write(str(file_number + 1))
    return file_number

def rotate_image_ocr(path):
    images = [Image.open(path)]
    text = pytesseract.image_to_string(images[-1])
    ocr_extractions = [text]
    for i in range(3):
        images.append(images[-1].rotate(90))
        text = pytesseract.image_to_string(images[-1])
        ocr_extractions.append(text)
    images_zip_ocr = [list(pair) for pair in zip(images, ocr_extractions)]
    return images_zip_ocr

def count_occurrences(images_zip_ocr):
    occurrences = []
    for img_txt_pair in images_zip_ocr:
        ocr_text = img_txt_pair[1]
        num_occurrences = ocr_text.lower().count('the')
        occurrences.append(num_occurrences)
    return occurrences

def isolate_correct_img_ocr(path):
    images_zip_ocr = rotate_image_ocr(path)
    occurrences_of_the = count_occurrences(images_zip_ocr)
    index_of_pair = occurrences_of_the.index(max(occurrences_of_the))
    img_ocr = images_zip_ocr[index_of_pair]
    return img_ocr

def run_image(file, metadata):
    # create the new Document
    doc = Document(file)
    doc.metadata = metadata
    doc.metadata[METADATA_FILE_NAME_FIELD] = doc.image_file
    # run OCR, update the doc, and write the file
    img_ocr = isolate_correct_img_ocr(doc.image_path)
    doc.text = img_ocr[1]
    doc.write_text_file()
    # save the image in the right place
    img_ocr[0].save(doc.image_path)
    # upload image to Flickr
    indent_print("Uploading to Flickr...", indent=2)
    flickr_dict = upload_image(doc.image_path)
    doc.metadata.update(flickr_dict)
    # update master metadata file
    with open(METADATA_FILE, "a") as file:
        file.write(doc.metadata_string())
        file.write("\n")
        file.write("\n")
    return doc

def run_folder_images(path):
    new_documents = []
    metadata = read_folder_metadata(path)
    for file in os.listdir(path):
        old_file_path = os.path.join(path, file)
        image_type = imghdr.what(old_file_path)
        if image_type:
            indent_print("{} is a {} file; running OCR...".format(file, image_type), indent=2)
            # build the new file path
            file_ext = file.split(".")[1]
            count = request_new_file_number()
            new_file_name = 'document' + str(count) + 'image.' + file_ext
            new_file_path = os.path.join(DEST_PATH, new_file_name)
            # move the file first
            os.rename(old_file_path, new_file_path)
            # create a document and do OCR
            doc = run_image(new_file_name, copy.copy(metadata))
            new_documents.append(doc)
    shutil.rmtree(path)
    return new_documents

def run_images():
    indent_print("Running OCR on images...", indent=0)
    new_documents = []
    for folder in os.listdir(LOADING_ZONE):
        path = os.path.join(LOADING_ZONE, folder)
        if os.path.isdir(path):
            indent_print("Looking at folder {}...".format(folder), indent=1)
            if not text_file_exists(path):
                indent_print("No metadata file found; skipping...", indent=2)
                continue
            metadata = read_folder_metadata(path)
            if all(s == "" for s in metadata.values()):
                indent_print("Metadata file is empty; skipping...", indent=2)
                continue
            new_documents.extend(run_folder_images(path))
    return new_documents

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.realpath(__file__)))
    indent_print("Initializing...", indent=0)
    download_flickr_images()
    run_images()
    print()
    indent_print("Done!", indent=0)
