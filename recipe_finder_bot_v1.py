import os
import json
import csv
import re
import sqlite3

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.dispatcher.filters import Text
from dotenv import load_dotenv


# список наименований рецептов
name_list = []

# словарь с заголовками рецептов
title_dict = {}

# словарь с описаниями рецептов
description_dict = {}

# словарь с ингредиентами рецептов
ingredients_dict = {}

# словарь с технологиями приготовления рецептов
recipe_dict = {}

# список всех возможных ингредиентов
all_ingredients = []

# считываем csv файл, заполняем списки и словари
with open("data/data.csv", encoding='utf-8') as file:
    data_base = csv.DictReader(file, delimiter=",")
    for row in data_base:
        name_list.append(row['name'])
        title_dict[row['name']] = row['title']
        description_dict[row['name']] = json.loads(row['description'].replace("'", '"'))
        ingredients_dict[row['name']] = json.loads(row['ingredients'].replace("'", '"'))
        recipe_dict[row['name']] = row['recipe'][3:-3].split("', '")
        for i in json.loads(row['ingredients'].replace("'", '"')):
            if i.lower() not in all_ingredients:
                all_ingredients.append(i.lower())

# создаем базу данных с идентификаторами пользователей, запросов и списками найденных по запросу рецептов
con = sqlite3.connect('db.sqlite')
cur = con.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS requests '
            '(user_id INTEGER, message_id INTEGER, recipe_list TEXT);')
con.commit()
con.close()

# создаем и запускаем бота
load_dotenv()
TOKEN = os.getenv('TOKEN')
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)


@dp.message_handler(commands='start')
async def start(message: types.Message):
    """В ответ на команду /start выводит сообщение-приветствие."""
    count = len(name_list)
    await message.answer(f"Привет. Я кулинарный бот.\n"
                         f"С моей помощью ты сможешь найти рецепты под имеющиеся у тебя продукты.\n"
                         f"Сейчас в моей базе собрано {count} рецептов.")
    await message.answer("Напиши названия ингредиентов через запятую:")


@dp.message_handler(commands='help')
async def help(message: types.Message):
    """В ответ на команду /help выводит сообщение-подсказку."""
    await message.answer("Напиши названия ингредиентов через запятую:")


async def on_startup(dispatcher):
    """Добавляет вызов команд /start и /help через меню."""
    await bot.set_my_commands([
        types.BotCommand("start", "Приветствие"),
        types.BotCommand("help",  "Помощь")
    ])


@dp.message_handler()
async def recipe_finder(message: types.Message):
    """Обрабатывает набранные сообщения."""

    # получаем список ингредиентов из сообщения
    get_ingredients = message.text.replace('.', ',').split(',')

    # создаем список ингредиентов прошедших проверку (имеются в списке ингредиентов)
    verified_ingredients = []

    # создаем список ингредиентов не прошедших проверку
    unverified_ingredients = []

    # проверяем ингредиенты на соответствие списку ингредиентов
    for ingredient in get_ingredients:
        ingredient = ingredient.lower().strip()
        for i in all_ingredients:
            if re.findall(ingredient, i) and ingredient not in verified_ingredients:
                verified_ingredients.append(ingredient)
        if ingredient not in verified_ingredients:
            unverified_ingredients.append(ingredient)

    # если в запросе присутствуют не прошедшие проверку ингредиенты, выводим их и просим изменить запрос
    if len(unverified_ingredients) >= 1:
        unverified_ingredients = ', '.join([i for i in unverified_ingredients])
        await message.answer(f'"{unverified_ingredients}": увы, таких ингредиентов нет в книге рецептов.\n'
                             f'Попробуйте изменить запрос.')
        return

    # ищем рецепты включающие запрошенные ингредиенты
    # создаем список найденных рецептов
    recipe_list = []

    def find_next_recipe(ingredient, recipe_list):
        """Ищет рецепты включающие в себя искомый ингредиент"""
        verified_recipe = []
        i = ingredient.lower()
        for r in recipe_list:
            j = ' '.join(ingredients_dict[r]).lower()
            if re.findall(i, j) and recipe not in verified_recipe:
                verified_recipe.append(r)
        return verified_recipe

    # проводим поиск по первому ингредиенту
    i = verified_ingredients[0]
    for recipe, ingredients in ingredients_dict.items():
        j = ' '.join(ingredients).lower()
        if re.findall(i, j) and recipe not in recipe_list:
            recipe_list.append(recipe)

    # проводим поиск по остальным ингредиентам, если они есть. Поиск проводится в результатах предыдущих поисков.
    if len(verified_ingredients) > 1:
        verified_ingredients = verified_ingredients[1:]
        for i in verified_ingredients:
            recipe_list = find_next_recipe(i, recipe_list)

    # Выводим сообщение с результатами поиска.
    if len(recipe_list) == 0:
        await message.answer('С таким сочетанием ингредиентов рецептов не найдено.\n'
                             'Попробуйте изменить запрос.')
    else:
        # создаем в базе данных запись в которой указываем идентификаторы пользователя, запроса и список рецептов
        con = sqlite3.connect('db.sqlite', check_same_thread=False)
        cur = con.cursor()
        cur.execute(
            'INSERT INTO requests VALUES (?, ?, ?);',
            (message.from_user.id, message.message_id,
             ','.join(recipe_list))
        )
        con.commit()
        con.close()

        # Создаем кнопку перехода на первую страницу с результатами поиска. Результаты передаем через callback_data.
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('Посмотреть найденные рецепты',
                                        callback_data=f"first&{message.message_id}"), )
        await message.answer(f'Найдено рецептов: {len(recipe_list)}', reply_markup=markup)


@dp.callback_query_handler(Text(startswith='first'))
async def first_page(callback: types.CallbackQuery):
    """Показывает первую страницу с рецептами."""

    # удаляем клавиатуру с оповещением о результатах поиска
    await bot.delete_message(callback.message.chat.id, callback.message.message_id)

    # получаем message_id из callback
    message_id = callback.data.split("&")[1]

    # для соответствующих идентификаторов пользователя и запроса получаем список рецептов из базы данных
    recipe_list = []
    con = sqlite3.connect('db.sqlite', check_same_thread=False)
    cur = con.cursor()
    cur.execute(f'SELECT * FROM requests WHERE user_id = {callback.from_user.id} AND message_id = {message_id}')
    for i in cur:
        recipe_list = i[2]
    con.commit()
    con.close()
    recipe_list = recipe_list.split(',')

    # создаем сообщение с первой страницей рецептов
    # количество рецептов (страниц)
    count = len(recipe_list)

    # номер страницы
    page = 1

    # индекс страницы
    num = page - 1

    # создаем клавиатуру
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text='Состав', callback_data=f'next_ingredients&{str(page)}&{message_id}'),
               InlineKeyboardButton(text='Скрыть', callback_data=f'unseen&{message_id}'),
               InlineKeyboardButton(text='Рецепт', callback_data=f'next_recipe&{str(page)}&{message_id}'))
    if count == 1:
        markup.add(InlineKeyboardButton(text=f'{page}/{count}', callback_data=f' '))
    else:
        markup.add(InlineKeyboardButton(text=f'{page}/{count}', callback_data=f' '),
                   InlineKeyboardButton(text=f'Вперёд --->',
                                        callback_data=f'next_pagination&{str(page + 1)}&{message_id}'))

    # наполняем первое сообщение заголовком, описанием и фотографией рецепта
    title = title_dict[recipe_list[num]]
    description = '\n'.join(description_dict[recipe_list[num]][1:])
    photo = f'data/image/{recipe_list[num]}.jpg'
    await bot.send_photo(callback.from_user.id, types.InputFile(photo),
                         caption=f'<b>{title}</b>\n<i>{description_dict[recipe_list[num]][0]}.</i>\n'
                                 f'{description}\n\n', parse_mode="HTML", reply_markup=markup)
    await callback.answer()


@dp.callback_query_handler(Text(startswith='unseen'))
async def unseen(callback: types.CallbackQuery):
    """Удаляет сообщение с рецептами."""

    # получаем message_id из callback
    message_id = callback.data.split("&")[1]

    # удаляем соответствующую запись из базы данных
    con = sqlite3.connect('db.sqlite', check_same_thread=False)
    cur = con.cursor()
    cur.execute(f'DELETE FROM requests WHERE message_id = {message_id}')
    con.commit()
    con.close()

    # удаляем сообщение из телеграмм
    await bot.delete_message(callback.message.chat.id, callback.message.message_id)
    await callback.answer()


@dp.callback_query_handler(text=' ')
async def nothing(callback: types.CallbackQuery):
    """Пустой callback. Ничего не делает. Заглушка."""
    await callback.answer()


@dp.callback_query_handler(Text(startswith='next'))
async def next_pages(callback: types.CallbackQuery):
    """Показывает остальные страницы с рецептами."""

    # преобразуем запрос в список и сохраняем в переменную
    req = callback.data.split('&')

    # получаем message_id из callback
    message_id = req[2]

    # для соответствующих идентификаторов пользователя и запроса получаем список рецептов из базы данных
    recipe_list = []
    con = sqlite3.connect('db.sqlite', check_same_thread=False)
    cur = con.cursor()
    cur.execute(f'SELECT * FROM requests WHERE user_id = {callback.from_user.id} AND message_id = {message_id}')
    for i in cur:
        recipe_list = i[2]
    con.commit()
    con.close()
    recipe_list = recipe_list.split(',')

    # количество рецептов (страниц)
    count = len(recipe_list)

    # номер страницы
    page = int(req[1])

    # индекс страницы
    num = page - 1

    # показываем ингредиенты рецепта если была нажата кнопка "Состав"
    if 'ingredients' in req[0]:
        ingredients = '\n'.join((i + ': ' + ingredients_dict[recipe_list[num]][i])
                                for i in ingredients_dict[recipe_list[num]])

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text='<--- Назад',
                                        callback_data=f'next_pagination&{str(page)}&{message_id}'))
        photo = f'data/image/{recipe_list[num]}.jpg'
        with open(photo, 'rb') as file:
            photo = types.InputMediaPhoto(file, caption=f'<b>Ингредиенты блюда:</b>\n'
                                                        f'{ingredients}\n\n', parse_mode="HTML")
            await bot.edit_message_media(media=photo, reply_markup=markup, chat_id=callback.message.chat.id,
                                         message_id=callback.message.message_id)
            await callback.answer()

    # показываем технологию приготовления рецепта если была нажата кнопка "Рецепт"
    elif 'recipe' in req[0]:
        recipe = '-  ' + '\n - '.join(recipe_dict[recipe_list[num]])
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text='<--- Назад',
                                        callback_data=f'next_pagination&{str(page)}&{message_id}'))
        photo = f'data/image/{recipe_list[num]}.jpg'
        with open(photo, 'rb') as file:
            photo = types.InputMediaPhoto(file, caption=f'<b>Технология приготовления блюда:</b>\n'
                                                        f'{recipe}\n\n', parse_mode="HTML")
            await bot.edit_message_media(media=photo, reply_markup=markup, chat_id=callback.message.chat.id,
                                         message_id=callback.message.message_id)
            await callback.answer()

    # отображаем текущий рецепт. Обрабатываем нажатия кнопок пагинации.
    elif 'pagination' in req[0]:

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text='Состав', callback_data=f'next_ingredients&{str(page)}&{message_id}'),
                   InlineKeyboardButton(text='Скрыть', callback_data=f'unseen&{message_id}'),
                   InlineKeyboardButton(text='Рецепт', callback_data=f'next_recipe&{str(page)}&{message_id}'))
        if count == 1:
            markup.add(InlineKeyboardButton(text=f'{page}/{count}', callback_data=f' '))
        elif page == 1:
            markup.add(InlineKeyboardButton(text=f'{page}/{count}', callback_data=' '),
                       InlineKeyboardButton(text=f'Вперёд --->',
                                            callback_data=f'next_pagination&{str(page + 1)}&{message_id}'))
        elif page == count:
            markup.add(InlineKeyboardButton(text=f'<--- Назад',
                                            callback_data=f'next_pagination&{str(page - 1)}&{message_id}'),
                       InlineKeyboardButton(text=f'{page}/{count}', callback_data=' '))
        else:
            markup.add(InlineKeyboardButton(text=f'<--- Назад',
                                            callback_data=f'next_pagination&{str(page - 1)}&{message_id}'),
                       InlineKeyboardButton(text=f'{page}/{count}', callback_data=' '),
                       InlineKeyboardButton(text=f'Вперёд --->',
                                            callback_data=f'next_pagination&{str(page + 1)}&{message_id}'))

        # наполняем сообщение заголовком, описанием и фотографией рецепта
        title = title_dict[recipe_list[num]]
        description = '\n'.join(description_dict[recipe_list[num]][1:])
        photo = f'data/image/{recipe_list[num]}.jpg'
        with open(photo, 'rb') as file:
            photo = types.InputMediaPhoto(file, caption=f'<b>{title}</b>\n'
                                                        f'<i>{description_dict[recipe_list[num]][0]}.</i>\n'
                                                        f'{description}\n\n', parse_mode="HTML")
            await bot.edit_message_media(media=photo, reply_markup=markup, chat_id=callback.message.chat.id,
                                         message_id=callback.message.message_id)
            await callback.answer()

if __name__ == '__main__':
    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup
    )
