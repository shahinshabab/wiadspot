"""Kerala towns used for location search and listing.

Towns only: there is deliberately no district level. The list covers the
municipalities and main commercial towns of all fourteen districts; the admin
can add more through the Django admin.
"""

KERALA_TOWNS = """
Thiruvananthapuram, Neyyattinkara, Attingal, Nedumangad, Varkala, Kazhakoottam, Kovalam, Vizhinjam,
Balaramapuram, Parassala, Kattakada, Vellarada, Pothencode, Kilimanoor, Venjaramoodu, Aryanad,
Kollam, Karunagappally, Paravur, Punalur, Kottarakkara, Chavara, Sasthamkotta, Kundara, Chadayamangalam,
Anchal, Pathanapuram, Oachira, Kadakkal, Thenmala, Ayoor,
Pathanamthitta, Adoor, Thiruvalla, Pandalam, Ranni, Konni, Kozhencherry, Mallappally, Aranmula, Pullad,
Alappuzha, Cherthala, Kayamkulam, Chengannur, Mavelikkara, Haripad, Ambalappuzha, Kuttanad, Thuravoor,
Aroor, Mannar, Harippad, Edathua, Muhamma,
Kottayam, Changanassery, Pala, Vaikom, Ettumanoor, Erattupetta, Kanjirappally, Ponkunnam, Mundakayam,
Kumarakom, Puthuppally, Ayarkunnam, Thalayolaparambu, Kuravilangad, Pampady,
Idukki, Thodupuzha, Munnar, Kattappana, Adimali, Nedumkandam, Peermade, Vandiperiyar, Kumily, Cheruthoni,
Rajakkad, Marayoor, Devikulam, Vagamon,
Kochi, Ernakulam, Aluva, Angamaly, Perumbavoor, Muvattupuzha, Kothamangalam, North Paravur, Tripunithura,
Kalamassery, Thrikkakara, Maradu, Piravom, Koothattukulam, Edappally, Vyttila, Fort Kochi, Mattancherry,
Kakkanad, Cheranalloor, Vypin, Kolenchery, Eloor, Pallikkara,
Thrissur, Chalakudy, Kodungallur, Irinjalakuda, Guruvayur, Kunnamkulam, Wadakkanchery, Chavakkad,
Ollur, Mala, Puthukkad, Mannuthy, Kechery, Thalikulam, Triprayar, Kodakara, Pazhayannur,
Palakkad, Ottapalam, Shoranur, Chittur, Mannarkkad, Alathur, Pattambi, Cherpulassery, Kollengode,
Nenmara, Malampuzha, Parli, Kuzhalmannam, Thrithala, Chalissery, Koduvayur, Vadakkencherry,
Malappuram, Manjeri, Perinthalmanna, Tirur, Ponnani, Nilambur, Kottakkal, Valanchery, Tanur,
Parappanangadi, Kondotty, Areekode, Tirurangadi, Edappal, Vengara, Chemmad, Pulamanthole, Mankada, Kuttippuram,
Kozhikode, Vadakara, Koyilandy, Ramanattukara, Feroke, Mukkam, Thamarassery, Balussery, Perambra,
Kunnamangalam, Nadapuram, Koduvally, Kuttiady, Quilandy, Elathur, Beypore, Mavoor,
Wayanad, Kalpetta, Sulthan Bathery, Mananthavady, Meenangadi, Vythiri, Pulpally, Panamaram, Ambalavayal, Kenichira,
Kannur, Thalassery, Payyannur, Taliparamba, Iritty, Mattannur, Koothuparamba, Panoor, Anjarakandy, Sreekandapuram,
Cherupuzha, Peravoor, Azhikode, Pappinissery, Kannapuram, Dharmadam,
Kasaragod, Kanhangad, Nileshwar, Manjeshwar, Uppala, Cheruvathur, Bekal, Cherkala, Badiadka, Kumbla, Neeleswaram,
Thrikkaripur, Vellarikundu, Mulleria
"""


def town_names():
    seen = []
    for raw in KERALA_TOWNS.replace("\n", " ").split(","):
        name = " ".join(raw.split())
        if name and name not in seen:
            seen.append(name)
    return seen
