#GUI library?
import customtkinter

def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.


if __name__ == '__main__':
    #Variables
    user = None
    pw = None
    isLoggedIn = False
    uin = None
    isQuitting = False

    #Login
    print("CSCI 320 Group 3 VGDB.\n")
    print("Please log in, or enter \"newuser\" to create an account.\n")
        #User
            #GOTO for account creation?
    while(not(isLoggedIn)):
            user = input("Username:")
        #Pass
            pw = input("Password:")
        #TODO: Loop on fail, validate login
            isLoggedIn = True


    #Main/Landing Page
    print("Welcome ",user,"!\n")
    while(not(isQuitting)):
        print("Type to access: [c]ollections, [g]ames, [p]lay, [r]ate, [s]ocial, [q]uit")
        uin = input()
        match uin:

        #Collections
            case "c" | "C":
                pass
            #Display collections by name ascending with stats
            #Input to create collection or go back

        #Games (Search)
            case "g" | "G":
                pass
            #Input Category (Name/Developer/Publisher/Platform/Release Date)
            #Input sort type or go back

        # Play
            case "p" | "P":
                pass
            # Input idx # for game or go back
                # Input playtime

        #Rate
            case "r" | "R":
                pass
            #Input idx # for game or go back
                #Input rating

        #Social
            case "s" | "S":
                pass
            #Input feed or search or go back
                #Feed
                    #Display recent reviews from followed, then go back after any input
                #Search
                    #Input user name and follow/unfollow if found, or go back

        #Quit
            case "q" | "Q":
                isQuitting = True

        #Default
            case _:
                print("Invalid input. Single letters only.")

    #Shutdown
    #Close connection properly!!!



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