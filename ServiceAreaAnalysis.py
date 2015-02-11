# !/usr/bin/env python
# -*- coding: utf-8 -*-
#--------------------------------------------------------------------------------------------------
# Name          : Localization of Care Service Area Aggregator
# Author        : Mark Pooley (mark-pooley@uiowa.edu)
# Link          : http://www.ppc.uiowa.edu
# Date          : 2015-02-02 16:40:29
# Version       : $1.1$
# Description   : Takes Service Areas and aggregates those below a user defined threshold. Those
# falling below the threshold are aggregated in no particular order. Assignment order isn't important
# since forward and backward assignments are check for. Once aggregated, instances of # "islands"
# (Service areas bounded entirely by another service area) are checked for and rectified.
#-------------------------------------------------------------------------------------------------

###################################################################################################
#Import python modules
###################################################################################################
import arcpy
from arcpy import env
from operator import itemgetter
env.overwriteOutput = True

###################################################################################################
#Input Variable loading and environment declaration
###################################################################################################
OriginalSA = arcpy.GetParameterAsText(0)
DSA_Field = arcpy.GetParameterAsText(1)
LOC_Field = arcpy.GetParameterAsText(2)
DyadTable = arcpy.GetParameterAsText(3)
DSARec_Field = arcpy.GetParameterAsText(4)
DSAProv_Field = arcpy.GetParameterAsText(5)
VisitsDyad_Field = arcpy.GetParameterAsText(6)
Threshold = arcpy.GetParameterAsText(7)
IowaBorder = arcpy.GetParameterAsText(8)
ZCTAs = arcpy.GetParameterAsText(9)
env.workspace = arcpy.GetParameterAsText(10)
OutputName = arcpy.GetParameterAsText(11)
OutputLocation = env.workspace

###################################################################################################
#Global variables to be used in process
###################################################################################################
DSARevised_Field = "Assigned_To_" + str(Threshold)[1:] + "pct" # string variable to make selection clauses easier
Assigned_List = [] #list of assignments
AssignedDict ={} #dictionary of assignments
DSA_Revised_List = []#revised list

###################################################################################################
#Sort the initial dataset by LOC so DSAs will be appended to a list in ascending order
#of LOC. The cursor selects all DSAs with an LOC below the defined threshold value
###################################################################################################
arcpy.SetProgressor("step","Setting up data...",0,3,1)
#check for presence of revised field
#check for revised field in Service Areas
if DSARevised_Field not in [f.name for f in arcpy.ListFields(OriginalSA)]:
    arcpy.AddField_management(OriginalSA,DSARevised_Field,"TEXT")
ServiceAreas_FieldList = [f.name for f in arcpy.ListFields(OriginalSA)] #Field list of service areas shapefile

#check fore revised field in ZCTAs
if DSARevised_Field not in [f.name for f in arcpy.ListFields(ZCTAs)]:
    arcpy.AddField_management(ZCTAs,DSARevised_Field,"TEXT")#add revised field to ZCTA table for creating a crosswalk
ZCTAFieldList = [f.name for f in arcpy.ListFields(ZCTAs)] #create list of from ZCTA fields

#arcpy.Sort_management(OriginalSA,"Temp_shapeFileSorted",[[LOC_Field,"ASCENDING"]])#sort by LOC field

arcpy.SetProgressorLabel("Creating 'DSA_Revised' field that will be used for reassignment.")

###################################################################################################
#Populate added field with all the DSAs above the user specified threshold and update the ZCTA file
###################################################################################################
#Selection clause used to populate DSA_Revised field
whereClause_UpdateCursor = LOC_Field + " > " + str(Threshold)

#populate DSA fields above threshold with current/correct assignment
arcpy.SetProgressorLabel("Populating DSA_Revised field with DSAs above the LOC: " + str(Threshold))
with arcpy.da.UpdateCursor(OriginalSA,[DSA_Field,DSARevised_Field,LOC_Field],whereClause_UpdateCursor) as cursor:
    for row in cursor:
        row[1] = row[0] #Populate DSA_Revised field with DSAs that are above the user specified threshold
        cursor.updateRow(row)
        Assigned_List.append(row[0])

#udpate ZCTAs for crosswalk as well.
with arcpy.da.UpdateCursor(ZCTAs,[DSA_Field,DSARevised_Field]) as cursor:
    for row in cursor:
        if row[0] in Assigned_List:
            row[1] = row[0]
            cursor.updateRow(row)

arcpy.SetProgressorPosition(1)

###################################################################################################
#Find DSAs in need of reassignment
###################################################################################################
arcpy.SetProgressorLabel("Finding DSAs in need of reassignment...")
LOC_query = LOC_Field + ' < ' + str(Threshold)#query to be used in cursor
DSA_List = [] #list to be populated with DSAs in need of reassignment

with arcpy.da.SearchCursor(OriginalSA,DSA_Field,LOC_query) as cursor:
    for row in cursor:
        DSA_List.append(row[0])

arcpy.AddMessage("{0} DSAs are in need of reassignment...".format(len(DSA_List)))

arcpy.SetProgressorPosition(2)
#Create a feature layer for the adjacent selection in the loop.
FeatureLayer = arcpy.MakeFeatureLayer_management(OriginalSA,"Temporary_Layer")

#create a dictionary that will house the DSAs that have been reassigned and what they've been
#reassigned to
arcpy.SetProgressorPosition(3)
arcpy.ResetProgressor()

###################################################################################################
#Reassigning DSAs below threshold
###################################################################################################

arcpy.SetProgressor("step","Reassiging DSAs",0,len(DSA_List),1)
#loop to reassign all the DSAs that are below the user specified threshold criteria
arcpy.AddMessage("Evaluating DSAs in need of reassignment...")

for i in range(0,len(DSA_List)):

    #-------------------------------------------------------------------------------------------
    #Variables for the loop
    #-------------------------------------------------------------------------------------------
    currentDSA = DSA_List[i] #current DSA variable
    whereClause = DSA_Field + " = '"+ str(currentDSA) + "'" #selection cluase
    DSA_RecClause = DSARec_Field + " = " + str(currentDSA) #where current DSA was recipient
    DSA_ProvClause = DSAProv_Field + " = " + str(currentDSA) #where current DSA was a Provider
    whereNotClause = DSA_Field + " <> " + "'" + currentDSA + "'" #select those not in question
    Adj_DSAs = [] #list to be populated with adjacent DSAs to the current one
    ProvDict = {} #dictionary of adjacent providers and visits occuring
    RecDict = {} #dictionary of care going to current DSA from adjacent DSAs
    FinalDict = {} #dictionary of additions where the best relationship will be found

    arcpy.SetProgressorLabel(str(currentDSA) + " being evaluated...")
    #-------------------------------------------------------------------------------------------
    #Select the current DSA and neighbors and create a list of neighbors
    #-------------------------------------------------------------------------------------------
    selection = arcpy.SelectLayerByAttribute_management(FeatureLayer,"NEW_SELECTION", whereClause)#select the current DSA
    Adjacent_Selection = arcpy.SelectLayerByLocation_management(FeatureLayer,"BOUNDARY_TOUCHES",selection,"#","NEW_SELECTION")#select neighbors

    #cursor to select the adjacent polygons that aren't the current Service Area
    with arcpy.da.SearchCursor(Adjacent_Selection,DSA_Field, whereNotClause) as cursor:
        for row in cursor:
            Adj_DSAs.append(row[0])

    #-------------------------------------------------------------------------------------------
    #Look in dyad table where recipient is the current DSA. Self assignment won't happen since the current
    #DSA is not in the adjacent list. Build two dictionarys, one where adjacent DSAs are providers
    #and another where adjacent DSAs were recipients. Go through both dictionarys and aggregate visits
    #occuring between the two and find the max number of visits
    #-------------------------------------------------------------------------------------------
    with arcpy.da.SearchCursor(DyadTable,[DSARec_Field,DSAProv_Field,VisitsDyad_Field],DSA_RecClause) as cursor:
        for row in cursor:
            if row[1] in Adj_DSAs:
                ProvDict[row[1]] = row[2]

    with arcpy.da.SearchCursor(DyadTable,[DSARec_Field,DSAProv_Field,VisitsDyad_Field],DSA_ProvClause) as cursor:
        for row in cursor:
            if row[0] in Adj_DSAs:
                RecDict[row[0]] = row[2]

    #-------------------------------------------------------------------------------------------
    #loop through adjacent list looking for keys in both of the generated dictionaries, add
    #corresponding visits and grab the maximum from the final dictionary
    #-------------------------------------------------------------------------------------------
    for i in Adj_DSAs:
        visits = 0 #tracker variable
        if i in ProvDict.keys():
            visits += ProvDict[i] #increment visits
        if i in RecDict.keys():
            visits += RecDict[i] #increment visits
        FinalDict[i] = visits #store the record

    maxDSA = max(FinalDict, key = FinalDict.get) #max DSA assignment
    del ProvDict # delete, since it's not needed
    del RecDict # delete, since it's not needed
    del FinalDict # delete, since it's not needed

   #-------------------------------------------------------------------------------------------
   #check that the max DSA isn't another DSA up for reassignment and that it hasn't already been
   #reassigned. If so, act accordingly, otherwise carry on.
   #-------------------------------------------------------------------------------------------
    if maxDSA in AssignedDict.keys():
        maxDSA = AssignedDict[maxDSA] #assign max DSA based on other DSA having been reassigned
        AssignedDict[currentDSA] = maxDSA
    else:
        AssignedDict[currentDSA] = maxDSA

    arcpy.SetProgressorLabel("{0} reassinged to {1}".format(currentDSA,maxDSA))

    #-------------------------------------------------------------------------------------------
    #Update the assignment fields in the orginal Service Areas, and the ZCTAs with max DSA for the
    #current selection
    #-------------------------------------------------------------------------------------------
    with arcpy.da.UpdateCursor(OriginalSA,[DSA_Field,DSARevised_Field],whereClause) as cursor:
        for row in cursor:
            row[1] = maxDSA
            cursor.updateRow(row)

    with arcpy.da.UpdateCursor(ZCTAs,ZCTAFieldList,whereClause) as cursor:
        for row in cursor:
            row[ZCTAFieldList.index(DSARevised_Field)] = maxDSA
            cursor.updateRow(row)

    DSA_Revised_List.append(currentDSA) #append Current DSA to Revised List
    arcpy.SetProgressorPosition()#set progressor position

arcpy.AddMessage("Checking for DSAs that were assigned to a Service Area that was later reassigned...")


####################################################################################################
#Check for forward assignment errors. That is, check that DSAs weren't assigned to another DSA
#that was later reassigned
####################################################################################################
arcpy.SetProgressor('step','Checking for Service Areas that were assigned to Service areas that were later reassigned...',0,len(AssignedDict),1)

for key,value in AssignedDict.iteritems():
    if value in AssignedDict.keys(): #look for value in keys - meaning that current key has been assigned to a DSA that was later reassigned
        SelectionClause = DSARevised_Field + " = '" + AssignedDict[key] + "'" #selection query, wanting the revised field to edit
        AssignedDict[key] = AssignedDict[value] #reassign accordingly
        ReAssignment = AssignedDict[value] #reassignment variable

        arcpy.SetProgressorLabel("{0} assignment corrected to {1}".format(AssignedDict[key],AssignedDict[value]))

        #update Service Areas and ZCTAs
        with arcpy.da.UpdateCursor(OriginalSA,DSARevised_Field,SelectionClause) as cursor:
            for row in cursor:
                row[0] = ReAssignment
                cursor.updateRow(row)
        with arcpy.da.UpdateCursor(ZCTAs,DSARevised_Field,SelectionClause) as cursor:
            for row in cursor:
                row[0] = ReAssignment
                cursor.updateRow(row)

        arcpy.SetProgressorPosition()
    else:
        arcpy.SetProgressorPosition()
        pass

arcpy.ResetProgressor()

####################################################################################################
#Clear selections and dissolve based on "Assigned_To" field
####################################################################################################
arcpy.SelectLayerByAttribute_management(FeatureLayer,"Clear_Selection")

arcpy.AddMessage("Dissolving current DSA reassignment...")

TempDissolve = arcpy.Dissolve_management(OriginalSA,"Temp_DSADissolve",DSARevised_Field,"","MULTI_PART","DISSOLVE_LINES")

####################################################################################################
#Look for DSAs that are entirely bounded by another service area. DSAs touching the border of the
#state are omitted from evaluation
####################################################################################################
arcpy.SetProgressor("step","Determining what DSAs touch the state border...",0,2,1)
arcpy.AddMessage("Looking for island DSAs...")

FeatureLayer = arcpy.MakeFeatureLayer_management(TempDissolve,"DSAFeatureLayer") #Make a feature layer so selections can be done

#Select Features touching the State Border then switch selection to get only those not touching the border.
BorderSelection = arcpy.SelectLayerByLocation_management(FeatureLayer,"WITHIN_A_DISTANCE",IowaBorder,"1 Miles","NEW_SELECTION")
BorderSelection = arcpy.SelectLayerByLocation_management(FeatureLayer,"WITHIN_A_DISTANCE",IowaBorder,"1 miles","SWITCH_SELECTION")

arcpy.SetProgressorLabel("Creating list of DSAs that don't touch the state boundary...")
arcpy.SetProgressorPosition()

DSAsToCheck = [] #list that will contain DSAs that don't touch border
with arcpy.da.SearchCursor(BorderSelection,DSARevised_Field) as cursor:
    for row in cursor:
        DSAsToCheck.append(row[0])

arcpy.SetProgressorPosition()
arcpy.ResetProgressor()

####################################################################################################
#Loop that will evaluate all DSAs not touching a border to determine if they are an island
####################################################################################################
IslandList = [] #list if islands
IslandDictionary = {} #create a dictionary of islands and the DSA they should be assigned to.
arcpy.SetProgressor("step","Checking DSAs that don't touch the border...",0,len(DSAsToCheck),1)

for i in range(len(DSAsToCheck)):

    currentDSA = DSAsToCheck[i] #loop variable to store current DSA
    #where clause generated through each iteration of the loop
    whereClause =  DSARevised_Field + " = " + "'" + str(currentDSA) + "'" #query for current DSA
    whereNotClause = DSARevised_Field + " <> " + "'" + str(currentDSA) + "'" #DSAs that aren't the current DSA

    arcpy.SetProgressorLabel("{0} does not touch boundary. Checking if DSA is an island".format(currentDSA))

    #-------------------------------------------------------------------------------------------
    #Select the current DSA, then all those with a boundary touching it.
    #look into doing this with a neighbor table...
    #-------------------------------------------------------------------------------------------
    selection = arcpy.SelectLayerByAttribute_management(FeatureLayer, "NEW_SELECTION", whereClause) #select current DSA
    Adjacent_Selection = arcpy.SelectLayerByLocation_management(FeatureLayer,"BOUNDARY_TOUCHES",selection,"#","NEW_SELECTION") #select features adjacent to the current selection

    #-------------------------------------------------------------------------------------------
    #look at adjacent selection and create a temporary list of all adjacent DSAs
    #-------------------------------------------------------------------------------------------
    TempList = [] #temp list for iterative process
    with arcpy.da.SearchCursor(Adjacent_Selection,DSARevised_Field, whereNotClause) as cursor:
        for row in cursor:
            TempList.append(str(row[0])) #append DSA revised field to Temp List

    #-------------------------------------------------------------------------------------------
    #if the length of the temp list is only 1, that means the DSA has only one neighbor and is
    #therefore an island
    #-------------------------------------------------------------------------------------------
    if len(TempList) == 1:
        IslandList.append(currentDSA)
        IslandDictionary[currentDSA] = TempList[0]

        arcpy.SetProgressorLabel('{0} is an island, reassigned to: {1}'.format(currentDSA,TempList[0]))

        with arcpy.da.UpdateCursor(OriginalSA,DSARevised_Field,whereClause) as cursor:
            for row in cursor:
                row[0] = IslandDictionary[currentDSA]
                cursor.updateRow(row)

        with arcpy.da.UpdateCursor(ZCTAs,DSARevised_Field,whereClause) as cursor:
            for row in cursor:
                row[0] = IslandDictionary[currentDSA]
                cursor.updateRow(row)

    else:
        pass

    arcpy.SetProgressorPosition()

arcpy.AddMessage("{0} DSAs were found to be islands and reassigned.".format(len(IslandList)))

####################################################################################################
#clean up data and export final outputs
####################################################################################################
#Clear selections to export the layer
arcpy.SelectLayerByAttribute_management(FeatureLayer,"Clear_Selection")

#dissolve the newly redifined service areas
arcpy.AddMessage("Dissolving into new service areas without islands...")
FinalOutput_Dissolve =  arcpy.Dissolve_management(OriginalSA,OutputName,DSARevised_Field,"#","MULTI_PART","DISSOLVE_LINES")


#Delete Temporary files created during the processing
arcpy.AddMessage("Removing Temporary files...")
arcpy.Delete_management(TempDissolve)

arcpy.AddMessage("DSA reassignment Complete!")
arcpy.AddMessage("Final output name: {0}".format(OutputName))
arcpy.AddMessage('Final ouput Location: {0}'.format(os.path.realpath(OutputLocation)))

