#GUI library?
#import PySimpleGUI as sg

def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.


if __name__ == '__main__':
    print_hi('PyCharm')

"""
Login
	Record date and time accessed
	Account creation
		Record date and time created
Main Page
	Collections
		Display all user's collections by name ascending
		Must show Name / # of games in collection / Total play time (in hours:minutes) of games in collection
		Create collection
	Search
		Search categories
			Text
				Name
				Developer
				Publisher
			Dropdown
				Platform
				Release Date (Calender?)
		Sort categories
	Rate
	Play
	Social
		Following feed?
			See followed reviews
				Sort by recency, first 5? How to implement with reasonable performance?
		Search for other users
			See their reviews
			Follow and unfollow other users
"""